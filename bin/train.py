from __future__ import absolute_import #??

import os
import time

from siamfc import TrackerSiamFC
from got10k.datasets import GOT10k

import multiprocessing

multiprocessing.set_start_method('spawn',True)

if __name__ == '__main__':
    begin = time.time()
    start=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(begin))
    print(">>>训练起始时间:{}".format(start))

    root_dir = os.path.abspath('data/GOT-10k')#获取当前工作目录
    #root_dir=r'E:\SiamFC-GOT-master\data\GOT-10k'
    seqs = GOT10k(root_dir, subset='train', return_meta=True)

    tracker = TrackerSiamFC(net_path=None) #优化器，GPU，损失函数，网络模型
    tracker.train_over(seqs)

    end = time.time()
    stop=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end))
    time_used = (end - begin)/60
    time_used_t=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_used))
    print(">>>训练起始时间:{}".format(start))
    print(">>>训练结束时间:{}".format(stop))
    print(">>>训练用时:{}分钟".format(time_used))
    print("================================================================================================================================\
     ======================================================================================================================================")
