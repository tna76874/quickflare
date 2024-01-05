#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan  5 12:33:09 2024
LMH (rewrite as class and for common use)
from:
https://raw.githubusercontent.com/UWUplus/flask-cloudflared/ad87527ddbde5eeecbd408bb0389847d17397671/flask_cloudflared.py
"""

import atexit
import requests
import subprocess
import tarfile
import tempfile
import shutil
import os
import platform
import time
import re
from random import randint
from threading import Timer
from pathlib import Path

class CloudflaredManager:
    def __init__(self, **kwargs):
        self.CLOUDFLARED_CONFIG = {
            ('Windows', 'AMD64'): {
                'command': 'cloudflared-windows-amd64.exe',
                'url': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
            },
            ('Windows', 'x86'): {
                'command': 'cloudflared-windows-386.exe',
                'url': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-386.exe'
            },
            ('Linux', 'x86_64'): {
                'command': 'cloudflared-linux-amd64',
                'url': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64'
            },
            ('Linux', 'i386'): {
                'command': 'cloudflared-linux-386',
                'url': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-386'
            },
            ('Linux', 'arm'): {
                'command': 'cloudflared-linux-arm',
                'url': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm'
            },
            ('Linux', 'arm64'): {
                'command': 'cloudflared-linux-arm64',
                'url': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64'
            },
            ('Linux', 'aarch64'): {
                'command': 'cloudflared-linux-arm64',
                'url': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64'
            },
            ('Darwin', 'x86_64'): {
                'command': 'cloudflared',
                'url': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz'
            },
            ('Darwin', 'arm64'): {
                'command': 'cloudflared',
                'url': 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz'
            }
        }
        
        self.port = kwargs.pop('port', 5000)
        self.host = kwargs.pop('host', '127.0.0.1')
        self.metrics_port = kwargs.pop('metrics_port', randint(8100, 9000))
        self.tunnel_id = kwargs.pop('tunnel_id', None)
        self.config_path = kwargs.pop('config_path', None)

    def _get_command(self, system, machine):
        try:
            return self.CLOUDFLARED_CONFIG[(system, machine)]['command']
        except KeyError:
            raise Exception(f"{machine} is not supported on {system}")

    def _get_url(self, system, machine):
        try:
            return self.CLOUDFLARED_CONFIG[(system, machine)]['url']
        except KeyError:
            raise Exception(f"{machine} is not supported on {system}")

    def _download_cloudflared(self, cloudflared_path, command):
        system, machine = platform.system(), platform.machine()
        if Path(cloudflared_path, command).exists():
            executable = (cloudflared_path+'/'+'cloudflared') if (system == "Darwin" and machine in ["x86_64", "arm64"]) else (cloudflared_path+'/'+command)
            update_cloudflared = subprocess.Popen([executable, 'update'], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            return
        print(f" * Downloading cloudflared for {system} {machine}...")
        url = self._get_url(system, machine)
        self._download_file(url)

    def _download_file(self, url):
        local_filename = url.split('/')[-1]
        r = requests.get(url, stream=True)
        download_path = str(Path(tempfile.gettempdir(), local_filename))
        with open(download_path, 'wb') as f:
            shutil.copyfileobj(r.raw, f)
        return download_path

    def _run_cloudflared(self):
        self.stop()
        
        port, metrics_port, tunnel_id, config_path = self.port, self.metrics_port, self.tunnel_id, self.config_path
        system, machine = platform.system(), platform.machine()
        command = self._get_command(system, machine)
        cloudflared_path = str(Path(tempfile.gettempdir()))
        if system == "Darwin":
            self._download_cloudflared(cloudflared_path, "cloudflared-darwin-amd64.tgz")
            self._extract_tarball(cloudflared_path, "cloudflared-darwin-amd64.tgz")
        else:
            self._download_cloudflared(cloudflared_path, command)
    
        executable = str(Path(cloudflared_path, command))
        os.chmod(executable, 0o777)
    
        cloudflared_command = [executable, 'tunnel', '--metrics', f'127.0.0.1:{metrics_port}']
        if config_path:
            cloudflared_command += ['--config', config_path, 'run']
        elif tunnel_id:
            cloudflared_command += ['--url', f'http://{self.host}:{port}', 'run', tunnel_id]
        else:
            cloudflared_command += ['--url', f'http://{self.host}:{port}']
    
        if system == "Darwin" and machine == "arm64":
            self.cloudflared = subprocess.Popen(['arch', '-x86_64'] + cloudflared_command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        else:
            self.cloudflared = subprocess.Popen(cloudflared_command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    
        atexit.register(self.cloudflared.terminate)
        self.localhost_url = f"http://127.0.0.1:{metrics_port}/metrics"
    
        for _ in range(10):
            try:
                metrics = requests.get(self.localhost_url).text
                if tunnel_id or config_path:
                    # If tunnel_id or config_path is provided, we check for cloudflared_tunnel_ha_connections, as no tunnel URL is available in the metrics
                    if re.search("cloudflared_tunnel_ha_connections\s\d", metrics):
                        # No tunnel URL is available in the metrics, so we return a generic text
                        tunnel_url = "preconfigured tunnel URL"
                        break
                else:
                    # If neither tunnel_id nor config_path is provided, we check for the tunnel URL in the metrics
                    tunnel_url = (re.search("(?P<url>https?:\/\/[^\s]+.trycloudflare.com)", metrics).group("url"))
                    break
            except:
                time.sleep(3)
        else:
            raise Exception(f"! Can't connect to Cloudflare Edge")
    
        self.tunnel_url = tunnel_url
        return tunnel_url
    
    def _print_info(self):
        print(f" * Running on {self.tunnel_url}")
        print(f" * Traffic stats available on http://127.0.0.1:{self.metrics_port}/metrics")
        
    def start(self, info = False):
        cloudflared_address = self._run_cloudflared()
        if info: self._print_info()
        
    def restart(self):
        pass
    
    def stop(self):
        try:
            self.cloudflared.terminate()
            self.cloudflared.kill()
            self.tunnel_url = None
        except:
            pass        
        
    def __del__(self):
        self.stop()
        
def main():
    import argparse
    parser = argparse.ArgumentParser(description='Cloudflared Quick Tunnel Manager')

    parser.add_argument('--port', type=int, default=5000, help='Specify the port (default: 5000)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Specify the host (default: 127.0.0.1)')
    parser.add_argument('--metrics-port', type=int, default=randint(8100, 9000), help='Specify the metrics port (default: random between 8100 and 9000)')
    parser.add_argument('--tunnel-id', type=str, default=None, help='Specify the tunnel ID (default: None)')
    parser.add_argument('--config-path', type=str, default=None, help='Specify the config path (default: None)')

    args = parser.parse_args()

    print("Starting up tunnel . . .")
    cManager = CloudflaredManager(**vars(args))
    cManager.start(info=True)

    print("Press CTRL+C to terminate tunnel")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    self = CloudflaredManager(port=5001)
    self.start(info=True)