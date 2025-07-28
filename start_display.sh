#!/bin/bash

# 設定顯示器
export DISPLAY=:0

# 檢查X server是否運行
if ! pgrep -x "X" > /dev/null; then
    echo "啟動X server..."
    sudo systemctl start lightdm
    sleep 3
fi

# 執行程式
echo "啟動顯示程式..."
python3 /root/PiSDBackup/display.py
