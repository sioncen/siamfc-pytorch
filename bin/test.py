from __future__ import absolute_import

import os
import time
from got10k.experiments import *

import multiprocessing
multiprocessing.set_start_method('spawn',True)

from siamfc import TrackerSiamFC


if __name__ == '__main__':
    begin = time.time()
    start = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(begin))
    print(">>>测试起始时间:{}".format(start))
    net_path = 'pretrained/'# 
    tracker = TrackerSiamFC(net_path=net_path) #初始化一个追踪器

    # root_dir = os.path.abspath('datasets/OTB')
    # e = ExperimentOTB(root_dir, version=2013)

    root_dir = os.path.abspath('datasets/OTB')
    e = ExperimentOTB(root_dir, version=2013)

    # root_dir = os.path.abspath('datasets/UAV123')
    # e = ExperimentUAV123(root_dir, version='UAV123')

    # root_dir = os.path.abspath('datasets/UAV123')
    # e = ExperimentUAV123(root_dir, version='UAV20L')

    # root_dir = os.path.abspath('datasets/DTB70')
    # e = ExperimentDTB70(root_dir)

    # root_dir = os.path.abspath('datasets/UAVDT')
    # e = ExperimentUAVDT(root_dir)

    # root_dir = os.path.abspath('datasets/VisDrone')
    # e = ExperimentVisDrone(root_dir)

    # root_dir = os.path.abspath('datasetssets/VOT2018')
    # e = ExperimentVOT(root_dir,version=2018)

    # root_dir = os.path.abspath('datasets/VOT2016')
    # e = ExperimentVOT(root_dir,version=2016)

    # root_dir = os.path.abspath('datasets/TColor128')
    # e = ExperimentTColor128(root_dir)

    # root_dir = os.path.abspath('datasets/Nfs')
    # e = ExperimentNfS(root_dir,fps=240) #高帧率

    #root_dir = os.path.abspath('datasets/LaSOT')
    #e = ExperimentLaSOT(root_dir)

    e.run(tracker,visualize=False)#默认不开启可视化

    e.report([tracker.name])

    end = time.time()
    stop = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end))
    time_used = (end - begin)/60
    time_used_t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time_used))
    print(net_path)
    print(">>>测试起始时间:{}".format(start))
    print(">>>测试结束时间:{}".format(stop))
    print(">>>测试用时:{}分钟".format(time_used))
    print("================================================================================================================================")
