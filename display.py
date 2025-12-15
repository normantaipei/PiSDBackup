#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
樹莓派觸控螢幕產品 - 完整解決方案
產品級介面，開機自動運行，直接顯示在螢幕上
"""

import os
import sys
import subprocess
import time
import threading
import signal
from pathlib import Path
import qrcode # QRコード生成のために追加

# 必要なパッケージの確認とインストール
def install_dependencies():
    """必要なパッケージの確認とインストール"""
    try:
        import pygame
        import psutil
        import qrcode # qrcodeもここでチェック
    except ImportError:
        print("必要なパッケージをインストールしています...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pygame', 'psutil', 'qrcode'])
        import pygame
        import psutil
        import qrcode

install_dependencies()

import pygame
import psutil
import socket
import re
from datetime import datetime
import json

# DEBUG_MODEを制御するためのグローバル変数
DEBUG_MODE = True # Trueに設定すると、デバッグ機能が有効になります

class DisplayManager:
    """ディスプレイマネージャー - さまざまなディスプレイ環境を処理"""

    def __init__(self):
        self.display_method = None
        self.setup_display()

    def setup_display(self):
        """ディスプレイ環境の設定"""
        print("ディスプレイ環境を設定しています...")
        
        # 方法1: 物理ディスプレイ接続の確認
        if self.setup_framebuffer():
            self.display_method = "framebuffer"
            return
        
        # 方法2: X11の使用 (利用可能な場合)
        if self.setup_x11():
            self.display_method = "x11"
            return
        
        # 方法3: 軽量Xサーバーの起動
        if self.setup_minimal_x11():
            self.display_method = "minimal_x11"
            return
        
        # 最終手段: 仮想ディスプレイの使用
        if self.setup_virtual_display():
            self.display_method = "virtual"
            return
        
        raise Exception("ディスプレイ環境を設定できませんでした")

    def setup_framebuffer(self):
        """フレームバッファディスプレイの設定"""
        try:
            # フレームバッファデバイスの確認
            if not os.path.exists('/dev/fb0'):
                return False
            
            # SDLがフレームバッファを使用するように設定
            os.environ['SDL_VIDEODRIVER'] = 'fbcon'
            os.environ['SDL_FBDEV'] = '/dev/fb0'
            os.environ['SDL_NOMOUSE'] = '1'  # 一時的にマウスを無効化
            
            # Pygameの初期化テスト
            pygame.init()
            screen = pygame.display.set_mode((480, 320))
            pygame.quit()
            
            print("✓ フレームバッファディスプレイが利用可能です")
            return True
            
        except Exception as e:
            print(f"✗ フレームバッファ設定に失敗しました: {e}")
            return False

    def setup_x11(self):
        """X11ディスプレイの設定"""
        try:
            # X11が実行中か確認
            result = subprocess.run(['pgrep', 'X'], capture_output=True)
            if result.returncode != 0:
                return False
            
            os.environ['DISPLAY'] = ':0'
            os.environ['SDL_VIDEODRIVER'] = 'x11'
            
            # Pygameの初期化テスト
            pygame.init()
            screen = pygame.display.set_mode((480, 320))
            pygame.quit()
            
            print("✓ X11ディスプレイが利用可能です")
            return True
            
        except Exception as e:
            print(f"✗ X11設定に失敗しました: {e}")
            return False

    def setup_minimal_x11(self):
        """最小X11環境の設定"""
        try:
            print("最小X11環境の起動を試行しています...")
            
            # Xサーバーの起動
            subprocess.run(['sudo', 'systemctl', 'start', 'lightdm'], 
                         capture_output=True, timeout=10)
            time.sleep(3)
            
            # 環境変数の設定
            os.environ['DISPLAY'] = ':0'
            os.environ['SDL_VIDEODRIVER'] = 'x11'
            
            # Pygameの初期化テスト
            pygame.init()
            screen = pygame.display.set_mode((480, 320))
            pygame.quit()
            
            print("✓ 最小X11環境の起動に成功しました")
            return True
            
        except Exception as e:
            print(f"✗ 最小X11環境の設定に失敗しました: {e}")
            return False

    def setup_virtual_display(self):
        """仮想ディスプレイの設定"""
        try:
            # Xvfbのインストールと使用
            subprocess.run(['sudo', 'apt', 'install', '-y', 'xvfb'], 
                         capture_output=True)
            
            # 仮想ディスプレイの起動
            subprocess.Popen(['Xvfb', ':99', '-screen', '0', '480x320x24'])
            time.sleep(2)
            
            os.environ['DISPLAY'] = ':99'
            os.environ['SDL_VIDEODRIVER'] = 'x11'
            
            # Pygameの初期化テスト
            pygame.init()
            screen = pygame.display.set_mode((480, 320))
            pygame.quit()
            
            print("✓ 仮想ディスプレイの起動に成功しました")
            return True
            
        except Exception as e:
            print(f"✗ 仮想ディスプレイの設定に失敗しました: {e}")
            return False

class RPiProductInterface:
    """Raspberry Pi製品インターフェース - メインアプリケーションクラス"""

    def __init__(self, display_manager):
        self.display_manager = display_manager
        self.running = True
        self.qr_code_surface = None # QRコードのSurfaceを保持
        self.setup_pygame()
        self.setup_ui()
        self.setup_data()
        self.setup_auto_startup()

    def setup_pygame(self):
        """Pygameの初期化"""
        pygame.init()
        pygame.font.init()
        
        # ディスプレイ方法に基づいて画面を設定
        if self.display_manager.display_method == "framebuffer":
            # フレームバッファモード - フルスクリーン
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self.width, self.height = self.screen.get_size()
        else:
            # その他のモード - 固定サイズ
            self.width, self.height = 480, 320
            self.screen = pygame.display.set_mode((self.width, self.height))
        
        pygame.display.set_caption("Raspberry Pi 監視システム")
        
        # マウスカーソルを非表示にする（製品モード）
        pygame.mouse.set_visible(False)
        
        print(f"✓ 画面の初期化が完了しました: {self.width}x{self.height}")

    def setup_ui(self):
        """UI要素の設定"""
        # フォント
        try:
            self.font_large = pygame.font.Font(None, 32)
            self.font_medium = pygame.font.Font(None, 24)
            self.font_small = pygame.font.Font(None, 18)
            self.font_tiny = pygame.font.Font(None, 14) # 日付/時刻用
        except:
            self.font_large = pygame.font.SysFont(None, 32)
            self.font_medium = pygame.font.SysFont(None, 24)
            self.font_small = pygame.font.SysFont(None, 18)
            self.font_tiny = pygame.font.SysFont(None, 14)
        
        # カラーテーマ
        self.colors = {
            'bg': (30, 30, 30),           # ダークグレーの背景
            'card': (45, 45, 45),         # カードの背景
            'accent': (0, 150, 255),      # メインのアクセントカラー
            'success': (0, 200, 100),     # 成功状態
            'warning': (255, 180, 0),     # 警告状態
            'error': (255, 80, 80),       # エラー状態
            'text': (255, 255, 255),      # メインテキスト
            'text_dim': (180, 180, 180),  # セカンダリテキスト
        }
        
        # レイアウトの計算
        self.layout = {
            'header_height': 40, # ヘッダーを小さく
            'card_margin': 10,
            'card_padding': 15,
        }
        
        # タッチエリア（再起動などの操作用） - DEBUG_MODEでのみ表示
        self.touch_areas = {
            'restart': pygame.Rect(self.width - 60, 5, 50, 30),
            'refresh': pygame.Rect(self.width - 120, 5, 50, 30),
        }

    def setup_data(self):
        """データ管理の設定"""
        self.data = {
            'ip_address': 'ロード中...',
            'wifi_ssid': 'ロード中...',
            'connection_status': 'チェック中...',
            'usb_devices': [],
            'system_info': {},
            'battery_info': {}, # バッテリー情報用
            'last_update': time.time()
        }
        
        # データ更新スレッドの起動
        self.data_thread = threading.Thread(target=self.data_update_loop, daemon=True)
        self.data_thread.start()
        
        # 一度すぐに更新
        self.update_data()

    def setup_auto_startup(self):
        """起動時の自動起動を設定"""
        startup_script = f"""#!/bin/bash
# Raspberry Pi モニターシステムの自動起動スクリプト

cd {os.path.dirname(os.path.abspath(__file__))}
python3 {os.path.abspath(__file__)}
"""

        # 起動スクリプトの作成
        script_path = "/home/pi/start_monitor.sh"
        try:
            with open(script_path, 'w') as f:
                f.write(startup_script)
            os.chmod(script_path, 0o755)
            
            # systemdサービスの作成
            service_content = f"""[Unit]
Description=Pi Touch Monitor
After=graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
User=pi
Environment=DISPLAY=:0
ExecStart={script_path}
Restart=always
RestartSec=3

[Install]
WantedBy=graphical-session.target
"""

            service_path = "/etc/systemd/system/pi-monitor.service"
            with open(service_path, 'w') as f:
                f.write(service_content)
            
            # サービスの有効化
            subprocess.run(['sudo', 'systemctl', 'enable', 'pi-monitor.service'], 
                         capture_output=True)
            
            print("✓ 起動時の自動起動を設定しました")
            
        except Exception as e:
            print(f"警告: 自動起動を設定できませんでした - {e}")

    def get_local_ip(self):
        """ローカルIPアドレスを取得"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "IP取得不可"

    def get_wifi_ssid(self):
        """WiFi SSIDを取得"""
        try:
            result = subprocess.run(['iwconfig'], capture_output=True, text=True, timeout=5)
            match = re.search(r'ESSID:"([^"]*)"', result.stdout)
            if match:
                ssid = match.group(1)
                return ssid if ssid else "WiFi未接続"
            return "WiFi未接続"
        except:
            return "SSID取得不可"

    def get_usb_devices(self):
        """USBデバイスを取得"""
        try:
            devices = []
            for partition in psutil.disk_partitions():
                if ('/media' in partition.mountpoint or 
                    '/mnt' in partition.mountpoint or
                    partition.fstype in ['vfat', 'exfat', 'ntfs']):
                    
                    try:
                        usage = psutil.disk_usage(partition.mountpoint)
                        devices.append({
                            'name': os.path.basename(partition.device),
                            'mount': partition.mountpoint,
                            'total': usage.total / (1024**3),
                            'used': usage.used / (1024**3),
                            'free': usage.free / (1024**3),
                            'percent': (usage.used / usage.total) * 100
                        })
                    except:
                        continue
            return devices
        except:
            return []

    def get_system_info(self):
        """システム情報を取得"""
        try:
            # 温度のみを保持
            temp = "N/A"
            try:
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    temp = f"{int(f.read()) / 1000:.1f}°C"
            except:
                pass
            
            return {
                'temp': temp,
            }
        except:
            return {}

    def get_battery_info(self):
        """バッテリー情報を取得"""
        try:
            # Primary: psutil
            battery = psutil.sensors_battery()
            if battery:
                return {
                    'percent': battery.percent,
                    'power_plugged': battery.power_plugged,
                    'secsleft': battery.secsleft,
                }

            # Fallback: read from sysfs (/sys/class/power_supply)
            ps_path = '/sys/class/power_supply'
            if os.path.isdir(ps_path):
                for name in os.listdir(ps_path):
                    p = os.path.join(ps_path, name)
                    cap_file = os.path.join(p, 'capacity')
                    status_file = os.path.join(p, 'status')
                    if os.path.isfile(cap_file):
                        try:
                            with open(cap_file, 'r') as f:
                                cap = f.read().strip()
                            percent = int(cap)
                        except:
                            continue

                        power_plugged = None
                        if os.path.isfile(status_file):
                            try:
                                with open(status_file, 'r') as f:
                                    st = f.read().strip().lower()
                                power_plugged = (st in ('charging', 'full'))
                            except:
                                power_plugged = None

                        return {
                            'percent': percent,
                            'power_plugged': power_plugged,
                            'secsleft': None,
                        }

            return {}
        except Exception:
            return {}

    def update_data(self):
        """すべてのデータを更新"""
        self.data['ip_address'] = self.get_local_ip()
        self.data['wifi_ssid'] = self.get_wifi_ssid()
        self.data['usb_devices'] = self.get_usb_devices()
        self.data['system_info'] = self.get_system_info()
        self.data['battery_info'] = self.get_battery_info() # バッテリー情報を更新
        
        # 接続状態を更新
        if (self.data['ip_address'] != "IP取得不可" and 
            self.data['wifi_ssid'] not in ["WiFi未接続", "SSID取得不可"]):
            self.data['connection_status'] = "接続済み"
        else:
            self.data['connection_status'] = "接続異常"
        
        self.data['last_update'] = time.time()
        self.generate_qr_code() # データ更新時にQRコードを再生成

    def data_update_loop(self):
        """データ更新ループ"""
        while self.running:
            try:
                self.update_data()
                time.sleep(3)  # 3秒ごとに更新
            except Exception as e:
                # print(f"データ更新ループエラー: {e}")
                time.sleep(5)

    def generate_qr_code(self):
        """QRコードを生成してPygameのSurfaceに変換"""
        ip = self.data['ip_address']
        if ip != "IP取得不可":
            qr_data = f"http://{ip}:5000" # 接続先URL
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=3, # QRコードのサイズを調整
                border=1, # 境界線
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
            
            # PILイメージをPygame Surfaceに変換
            self.qr_code_surface = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
        else:
            self.qr_code_surface = None

    def draw_header(self):
        """上部ヘッダーバーの描画"""
        header_rect = pygame.Rect(0, 0, self.width, self.layout['header_height'])
        pygame.draw.rect(self.screen, self.colors['card'], header_rect)
        
        # 現在の日付と時刻
        current_datetime = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        datetime_text = self.font_tiny.render(current_datetime, True, self.colors['text_dim'])
        datetime_rect = datetime_text.get_rect()
        self.screen.blit(datetime_text, (self.width - datetime_rect.width - 10, 
                                        self.layout['header_height'] // 2 - datetime_rect.height // 2))
        
        # デバッグモードの場合のみボタンを表示
        if DEBUG_MODE:
            # 更新ボタン
            pygame.draw.rect(self.screen, self.colors['accent'], self.touch_areas['refresh'])
            refresh_text = self.font_small.render("更新", True, self.colors['text'])
            refresh_rect = refresh_text.get_rect(center=self.touch_areas['refresh'].center)
            self.screen.blit(refresh_text, refresh_rect)

            # 再起動ボタン
            pygame.draw.rect(self.screen, self.colors['error'], self.touch_areas['restart'])
            restart_text = self.font_small.render("再起動", True, self.colors['text'])
            restart_rect = restart_text.get_rect(center=self.touch_areas['restart'].center)
            self.screen.blit(restart_text, restart_rect)


    def draw_network_card(self):
        """ネットワーク情報カードの描画"""
        y_start = self.layout['header_height'] + self.layout['card_margin']
        card_height = 100
        card_rect = pygame.Rect(self.layout['card_margin'], y_start, 
                               self.width - 2 * self.layout['card_margin'], card_height)
        
        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)
        
        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']
        
        # カードタイトル
        title = self.font_medium.render("ネットワーク状態", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += 25
        
        # IPアドレス
        ip_text = self.font_small.render(f"IP: {self.data['ip_address']}", True, self.colors['text'])
        self.screen.blit(ip_text, (x, y))

        # QRコードの描画
        if self.qr_code_surface:
            qr_x = card_rect.right - self.layout['card_padding'] - self.qr_code_surface.get_width()
            qr_y = card_rect.y + self.layout['card_padding'] + self.font_medium.get_height() // 2 # ヘッダーの中央に配置
            self.screen.blit(self.qr_code_surface, (qr_x, qr_y))
        
        y += 20
        
        # WiFi名
        wifi_text = self.font_small.render(f"WiFi: {self.data['wifi_ssid']}", True, self.colors['text'])
        self.screen.blit(wifi_text, (x, y))
        y += 20
        
        # 接続状態
        status_color = self.colors['success'] if self.data['connection_status'] == "接続済み" else self.colors['error']
        status_text = self.font_small.render(f"状態: {self.data['connection_status']}", True, status_color)
        self.screen.blit(status_text, (x, y))

    def draw_system_card(self):
        """システム情報カードの描画（温度とバッテリーのみ）"""
        y_start = self.layout['header_height'] + self.layout['card_margin'] * 2 + 100
        card_height = 80
        card_rect = pygame.Rect(self.layout['card_margin'], y_start, 
                               self.width // 2 - self.layout['card_margin'] * 1.5, card_height)
        
        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)
        
        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']
        
        # システム情報
        title = self.font_small.render("システム", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += 18
        
        if self.data['system_info']:
            sys_info = self.data['system_info']
            temp_text = self.font_small.render(f"温度: {sys_info.get('temp', 'N/A')}", True, self.colors['text'])
            self.screen.blit(temp_text, (x, y))
            y += 15
        
        # バッテリー情報
        if self.data['battery_info']:
            battery_info = self.data['battery_info']
            battery_percent = battery_info.get('percent', 'N/A')
            battery_text = self.font_small.render(f"バッテリー: {battery_percent:.1f}%", True, self.colors['text'])
            self.screen.blit(battery_text, (x, y))
        else:
            no_battery_text = self.font_small.render("バッテリー: N/A", True, self.colors['text_dim'])
            self.screen.blit(no_battery_text, (x, y))


    def draw_usb_card(self):
        """USBデバイスカードの描画"""
        y_start = self.layout['header_height'] + self.layout['card_margin'] * 2 + 100
        card_height = 80
        card_rect = pygame.Rect(self.width // 2 + self.layout['card_margin'] * 0.5, y_start, 
                               self.width // 2 - self.layout['card_margin'] * 1.5, card_height)
        
        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)
        
        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']
        
        # USBデバイス
        title = self.font_small.render("USBデバイス", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += 18
        
        if self.data['usb_devices']:
            for device in self.data['usb_devices'][:2]:  # 最大2つ表示
                name_text = self.font_small.render(device['name'], True, self.colors['text'])
                self.screen.blit(name_text, (x, y))
                y += 12
                
                size_text = self.font_small.render(f"{device['used']:.1f}/{device['total']:.1f}GB", 
                                                 True, self.colors['text_dim'])
                self.screen.blit(size_text, (x, y))
                y += 15
        else:
            no_usb_text = self.font_small.render("USBデバイスなし", True, self.colors['text_dim'])
            self.screen.blit(no_usb_text, (x, y))

    def draw_status_bar(self):
        """下部ステータスバーの描画"""
        y_start = self.height - 30
        status_rect = pygame.Rect(0, y_start, self.width, 30)
        pygame.draw.rect(self.screen, self.colors['card'], status_rect)
        
        # 更新時間
        update_time = datetime.fromtimestamp(self.data['last_update']).strftime("%H:%M:%S")
        update_text = self.font_small.render(f"更新: {update_time}", True, self.colors['text_dim'])
        self.screen.blit(update_text, (10, y_start + 8))
        
        # 実行状態インジケータ
        status_color = self.colors['success']
        pygame.draw.circle(self.screen, status_color, (self.width - 20, y_start + 15), 5)

    def handle_touch(self, pos):
        """タッチイベントの処理"""
        if DEBUG_MODE: # DEBUG_MODEの場合のみボタンを処理
            if self.touch_areas['refresh'].collidepoint(pos):
                print("手動でデータを更新しています")
                threading.Thread(target=self.update_data, daemon=True).start()
            elif self.touch_areas['restart'].collidepoint(pos):
                print("システムを再起動しています")
                subprocess.run(['sudo', 'reboot'])

    def run(self):
        """メイン実行ループ"""
        clock = pygame.time.Clock()
        
        print("✓ 製品インターフェースの起動が完了しました")
        print(f"表示方法: {self.display_manager.display_method}")
        print(f"解像度: {self.width}x{self.height}")
        
        try:
            while self.running:
                # イベントの処理
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            self.running = False
                        elif event.key == pygame.K_F5:
                            self.update_data()
                    elif event.type in [pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN]:
                        if event.type == pygame.MOUSEBUTTONDOWN:
                            self.handle_touch(event.pos)
                        else:
                            touch_pos = (int(event.x * self.width), int(event.y * self.height))
                            self.handle_touch(touch_pos)
                
                # 画面のクリア
                self.screen.fill(self.colors['bg'])
                
                # インターフェースの描画
                self.draw_header()
                self.draw_network_card()
                self.draw_system_card()
                self.draw_usb_card()
                self.draw_status_bar()
                
                # ディスプレイの更新
                pygame.display.flip()
                clock.tick(30)  # 30 FPS
                
        except KeyboardInterrupt:
            print("\nプログラムが中断されました")
        finally:
            self.running = False
            pygame.quit()

def setup_system():
    """システム設定 - Raspberry Piが最適な状態であることを確認"""
    print("システム設定をチェックしています...")

    # 必要なパッケージがインストールされていることを確認
    packages = ['python3-pygame', 'python3-psutil', 'python3-qrcode'] # qrcodeも追加
    for package in packages:
        try:
            result = subprocess.run(['dpkg', '-l', package], capture_output=True)
            if result.returncode != 0:
                print(f"{package}をインストールしています...")
                subprocess.run(['sudo', 'apt', 'install', '-y', package])
        except:
            pass

    # 自動ログインの設定（必要な場合）
    try:
        subprocess.run(['sudo', 'raspi-config', 'nonint', 'do_boot_behaviour', 'B4'], 
                     capture_output=True)
    except:
        pass

    print("✓ システム設定が完了しました")

def main():
    """メインプログラムのエントリポイント"""
    print("=" * 60)
    print("Raspberry Pi タッチスクリーン監視システム")
    print("=" * 60)

    # シグナルハンドリング
    def signal_handler(sig, frame):
        print("\nシャットダウンしています...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # システム設定
        setup_system()
        
        # ディスプレイマネージャーの初期化
        display_manager = DisplayManager()
        
        # 製品インターフェースの起動
        app = RPiProductInterface(display_manager)
        app.run()
        
    except Exception as e:
        print(f"起動に失敗しました: {e}")
        print("システム設定を確認して再試行してください")
        sys.exit(1)

if __name__ == "__main__":
    main()

