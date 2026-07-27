#!/usr/bin/env python3
"""
Watcher守护进程启动脚本
在后台持续运行watcher服务
"""

import sys
import time
import signal
import os
from pathlib import Path

# 添加src到路径
sys.path.insert(0, 'src')

from src.watcher.manager import get_watcher_manager
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/rag_watcher.log', mode='a')
    ]
)

logger = logging.getLogger(__name__)

def signal_handler(signum, frame):
    """信号处理"""
    logger.info(f"Received signal {signum}, stopping watcher...")
    manager = get_watcher_manager()
    if manager.get_status()['is_running']:
        manager.stop()
    sys.exit(0)

# 注册信号处理
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

def main():
    """主函数"""
    logger.info("Starting Watcher Daemon...")
    
    manager = get_watcher_manager()
    
    # 检查是否已在运行
    if manager.get_status()['is_running']:
        logger.info("Watcher is already running")
        print("Watcher is already running")
        return
    
    # 启动watcher
    result = manager.start()
    if not result['success']:
        logger.error(f"Failed to start watcher: {result['message']}")
        print(f"Failed to start watcher: {result['message']}")
        return
    
    logger.info(f"Watcher started: {result['message']}")
    print(f"Watcher started: {result['message']}")
    
    # 保持运行
    try:
        while True:
            time.sleep(1)
            # 检查watcher状态
            status = manager.get_status()
            if not status['is_running']:
                logger.error("Watcher stopped unexpectedly, restarting...")
                result = manager.start()
                if result['success']:
                    logger.info("Watcher restarted successfully")
                else:
                    logger.error(f"Failed to restart watcher: {result['message']}")
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, stopping...")
        manager.stop()
        logger.info("Watcher stopped")

if __name__ == '__main__':
    main()
