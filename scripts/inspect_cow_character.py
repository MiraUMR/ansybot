#!/usr/bin/env python3
import os, subprocess
os.chdir("/app")
def run(cmd):
    print(">>>", cmd)
    subprocess.run(cmd, shell=True)

run("grep -rn character_desc --include='*.py' . | grep -v __pycache__ | grep -v /tests/ | head -n 40")
run("grep -rn 'class ChatGPTSession' --include='*.py' . | grep -v __pycache__ | head -n 20")
run("ls plugins")
run("sed -n '1,90p' plugins/event.py")
