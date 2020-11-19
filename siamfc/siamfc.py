from __future__ import absolute_import, division, print_function

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np
import time
import cv2
import sys
import os
from collections import namedtuple
from torch.optim.lr_scheduler import ExponentialLR
from torch.utils.data import DataLoader
from got10k.trackers import Tracker   # GOT-10k

from . import ops
from .backbones import AlexNetV1
from .heads import SiamFC
from .losses import BalancedLoss
from .datasets import Pair
from .transforms import SiamFCTransforms


__all__ = ['TrackerSiamFC']


class Net(nn.Module):

    def __init__(self, backbone, head):
        super(Net, self).__init__()
        self.backbone = backbone
        self.head = head
    
    def forward(self, z, x):
        z = self.backbone(z)
        x = self.backbone(x)
        return self.head(z, x)

class TrackerSiamFC(Tracker):  #定义一个追踪器

    def __init__(self, net_path=None, **kwargs):
        super(TrackerSiamFC, self).__init__(net_path, True)

        self.cfg = self.parse_args(**kwargs)  #加载一些初始化的参数

        # setup GPU device if available
        self.cuda = torch.cuda.is_available()

        self.device = torch.device('cuda:0' if self.cuda else 'cpu') #指定 GPU0 来进行训练

        # setup model
        self.net = Net(
            backbone=AlexNetV1(),  
            head=SiamFC(self.cfg.out_scale))
        ops.init_weights(self.net) #对网络权重进行初始化？？？
        
        # load checkpoint if provided
        if net_path is not None:  #加载训练好的网络模型
            self.net.load_state_dict(torch.load(
                net_path, map_location=lambda storage, loc: storage))
        self.net = self.net.to(self.device) #将模型加载到GPU上

        # setup criterion
        self.criterion = BalancedLoss()

        # setup optimizer
        self.optimizer = optim.SGD(
            self.net.parameters(),
            lr=self.cfg.initial_lr,
            weight_decay=self.cfg.weight_decay,
            momentum=self.cfg.momentum)
        
        # setup lr scheduler  #动态调整学习率 这个是怎么计算的？？
        gamma = np.power(self.cfg.ultimate_lr / self.cfg.initial_lr, 1.0 / self.cfg.epoch_num)

        #gamma=0.87
        self.lr_scheduler = ExponentialLR(self.optimizer, gamma)

    def parse_args(self, **kwargs):
        # default parameters
        cfg = {
            # basic parameters
            'out_scale': 0.001,
            'exemplar_sz': 127, #第一帧
            'instance_sz': 255, #
            'context': 0.5,
            # inference parameters
            'scale_num': 3,
            'scale_step': 1.0375,
            'scale_lr': 0.59,
            'scale_penalty': 0.9745,
            'window_influence': 0.176,
            'response_sz': 17,
            'response_up': 16,
            'total_stride': 8,
            # train parameters
            'epoch_num': 50,
            'batch_size': 8,
            'num_workers': 8,  #原来是32 被我修改成8
            'initial_lr': 1e-2, #0.01
            'ultimate_lr': 1e-5,#0.000052
            'weight_decay': 5e-4,#正则参数
            'momentum': 0.9,
            'r_pos': 16,  #
            'r_neg': 0}   # 
        
        for key, val in kwargs.items():
            if key in cfg:
                cfg.update({key: val})
        return namedtuple('Config', cfg.keys())(**cfg) 
  
    #namedtuple比tuple更强大，与list不同的是,你不能改变tuple中元素的数值 
    #Namedtuple比普通tuple具有更好的可读性，可以使代码更易于维护
    #为了构造一个namedtuple需要两个参数，分别是tuple的名字和其中域的名字
     
    '''禁止计算局部梯度
    方法1 使用装饰器 @torch.no_gard()修饰的函数，在调用时不允许计算梯度
    方法2 # 将不用计算梯度的变量放在 with torch.no_grad()里
    '''
    @torch.no_grad()# 
    def init(self, img, box):
        # set to evaluation mode
        self.net.eval()

        # convert box to 0-indexed and center based [y, x, h, w]
        box = np.array([
            box[1] - 1 + (box[3] - 1) / 2,
            box[0] - 1 + (box[2] - 1) / 2,
            box[3], box[2]], dtype=np.float32)
        self.center, self.target_sz = box[:2], box[2:] #最原始的图片大小 从groundtruth读取

        # create hanning window  response_up=16 ；  response_sz=17 ； self.upscale_sz=272
        self.upscale_sz = self.cfg.response_up * self.cfg.response_sz  
        self.hann_window = np.outer(  # np.outer 如果a，b是高维数组，函数会自动将其flatten成1维 ，用来求外积
            np.hanning(self.upscale_sz),
            np.hanning(self.upscale_sz))
        self.hann_window /= self.hann_window.sum()  #？？？

        # search scale factors
        self.scale_factors = self.cfg.scale_step ** np.linspace( #linspace 在start和stop之间返回均匀间隔的数据
            -(self.cfg.scale_num // 2), #//py3中双斜杠代表向下取整
            self.cfg.scale_num // 2, self.cfg.scale_num)
        
        # exemplar and search sizes  self.cfg.context=1/2  
        context = self.cfg.context * np.sum(self.target_sz)    # 引入margin：2P=(长+宽）× 1/2
        self.z_sz = np.sqrt(np.prod(self.target_sz + context)) # ([长，宽]+2P) x 2 添加 padding  没有乘以缩放因子
        self.x_sz = self.z_sz *self.cfg.instance_sz / self.cfg.exemplar_sz  # 226   没有乘以缩放因子
        # z是初始模板的大小 x是搜索区域
        # exemplar image 
        self.avg_color = np.mean(img, axis=(0, 1)) # 计算RGB通道的均值,使用图像均值进行padding
        z = ops.crop_and_resize(img, self.center, self.z_sz,
            out_size=self.cfg.exemplar_sz,
            border_value=self.avg_color)
        
        #对所有的图片进行预处理，得到127x127大小的patch
        # exemplar features
        z = torch.from_numpy(z).to(self.device).permute(2, 0, 1).unsqueeze(0).float() 

        self.kernel = self.net.backbone(z)
    
    @torch.no_grad() #
    def update(self, img):
        # set to evaluation mode
        self.net.eval()

        # search images
        x = [ops.crop_and_resize(
            img, self.center, self.x_sz * f,
            out_size=self.cfg.instance_sz,
            border_value=self.avg_color) for f in self.scale_factors]
        x = np.stack(x, axis=0)
        x = torch.from_numpy(x).to(
            self.device).permute(0, 3, 1, 2).float()
        
        # responses
        x = self.net.backbone(x)
        responses = self.net.head(self.kernel, x)
        responses = responses.squeeze(1).cpu().numpy()


        # upsample responses and penalize scale changes
        responses = np.stack([cv2.resize(
            u, (self.upscale_sz, self.upscale_sz),
            interpolation=cv2.INTER_CUBIC)
            for u in responses])
        responses[:self.cfg.scale_num // 2] *= self.cfg.scale_penalty
        responses[self.cfg.scale_num // 2 + 1:] *= self.cfg.scale_penalty

        # peak scale
        scale_id = np.argmax(np.amax(responses, axis=(1, 2)))

        # peak location
        response = responses[scale_id]
        response -= response.min()
        response /= response.sum() + 1e-16
        response = (1 - self.cfg.window_influence) * response + \
            self.cfg.window_influence * self.hann_window
        loc = np.unravel_index(response.argmax(), response.shape)

        # locate target center
        disp_in_response = np.array(loc) - (self.upscale_sz - 1) / 2
        disp_in_instance = disp_in_response * \
            self.cfg.total_stride / self.cfg.response_up
        disp_in_image = disp_in_instance * self.x_sz * \
            self.scale_factors[scale_id] / self.cfg.instance_sz
        self.center += disp_in_image

        # update target size
        scale =  (1 - self.cfg.scale_lr) * 1.0 + self.cfg.scale_lr * self.scale_factors[scale_id]
        self.target_sz *= scale
        self.z_sz *= scale
        self.x_sz *= scale

        # return 1-indexed and left-top based bounding box  [x,y,w,h]
        box = np.array([
            self.center[1] + 1 - (self.target_sz[1] - 1) / 2,
            self.center[0] + 1 - (self.target_sz[0] - 1) / 2,
            self.target_sz[1], self.target_sz[0]])

        return box
    
    def track(self, img_files, box, visualize=False):  # x,y,w,h
        frame_num = len(img_files)
        boxes = np.zeros((frame_num, 4))
        boxes[0] = box
        times = np.zeros(frame_num)

        for f, img_file in enumerate(img_files):
            img = ops.read_image(img_file)
            begin = time.time()
            if f == 0:
                self.init(img, box)
            else:
                boxes[f, :] = self.update(img)
            times[f] = time.time() - begin

            if visualize:
                ops.show_image(img, boxes[f, :])

        return boxes, times
    
    def train_step(self, batch, backward=True):
        # set network mode
        self.net.train(backward) # 训练模式
        # img_np = batch[0].numpy()
        # img_np = img_np[0].transpose([1, 2, 0])  # 取出其中一张并转换维度
        # img_np = (img_np - np.min(img_np)) / (np.max(img_np) - np.min(img_np)) * 127.0  # 转为0-255
        # img_np = img_np.astype('uint8')  # 转换数据类型
        # cv2.imshow('./1.jpg', img_np)  # 保存为图片img_np = batch[0].numpy()
        # img_np2 = batch[1].numpy()
        # img_np2 = img_np2[0].transpose([1, 2, 0])  # 取出其中一张并转换维度
        # img_np2 = (img_np2 - np.min(img_np2)) / (np.max(img_np2) - np.min(img_np2)) * 255.0  # 转为0-255
        # img_np2 = img_np2.astype('uint8') # 转换数据类型
        # cv2.imshow('./2.jpg', img_np2)  # 保存为图片
        # cv2.waitKey(0)
        # parse batch data
        z = batch[0].to(self.device, non_blocking=self.cuda)
        x = batch[1].to(self.device, non_blocking=self.cuda)

        with torch.set_grad_enabled(backward):
            # inference
            responses = self.net(z, x)

            # calculate loss
            labels = self._create_labels(responses.size())
            loss = self.criterion(responses, labels)
            
            if backward:
                # back propagation
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()
        
        return loss.item()

    # 在禁止计算梯度下调用被允许计算梯度的函数
    @torch.enable_grad()
    def train_over(self, seqs, val_seqs=None,save_dir='pretrained'):
        # set to train mode
        self.net.train()
        # create save_dir folder
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        # setup dataset
        transforms = SiamFCTransforms(
            exemplar_sz=self.cfg.exemplar_sz, #127
            instance_sz=self.cfg.instance_sz, #255
            context=self.cfg.context)  # 0.5 ？？？

        dataset = Pair(seqs=seqs,transforms=transforms)

        # setup dataloader
        dataloader = DataLoader(
            dataset,
            batch_size=self.cfg.batch_size,
            shuffle=True,
            num_workers=self.cfg.num_workers,
            pin_memory=self.cuda,
            drop_last=True)
        
        # loop over epochs
        for epoch in range(self.cfg.epoch_num):
            loss_sum = 0.0
            # loop over dataloader
            for it, batch in enumerate(dataloader):
                loss = self.train_step(batch, backward=True)
                loss_sum += loss
                print('Epoch: {} [{}/{}] Loss: {:.5f}'.format(epoch + 1, it + 1, len(dataloader), loss))
                sys.stdout.flush()

            loss_avg = loss_sum / len(dataloader)

            if (epoch > 39):
                net_path = os.path.join(save_dir, '{:.5f}_{:.5f}_{}.pth'.format(loss_avg, loss, epoch + 1))
                torch.save(self.net.state_dict(), net_path)

            # update lr at each epoch
            self.lr_scheduler.step(epoch=epoch)

    
    def _create_labels(self, size):
        # skip if same sized labels already created
        if hasattr(self, 'labels') and self.labels.size() == size:

            return self.labels

        def logistic_labels(x, y, r_pos, r_neg):

            dist = np.abs(x) + np.abs(y)  # block distance

            labels = np.where(dist <= r_pos,
                              np.ones_like(x),
                              np.where(dist < r_neg,np.ones_like(x) * 0.5,np.zeros_like(x)))

            return labels

        # distances along x- and y-axis
        n, c, h, w = size
        x = np.arange(w) - (w - 1) / 2
        y = np.arange(h) - (h - 1) / 2
        x, y = np.meshgrid(x, y)

        # create logistic labels
        r_pos = self.cfg.r_pos / self.cfg.total_stride
        r_neg = self.cfg.r_neg / self.cfg.total_stride
        labels = logistic_labels(x, y, r_pos, r_neg)

        # repeat to size
        labels = labels.reshape((1, 1, h, w))
        labels = np.tile(labels, (n, c, 1, 1))

        # convert to tensors
        self.labels = torch.from_numpy(labels).to(self.device).float()
        
        return self.labels
