# -*- coding: utf-8 -*-
"""
AI 協作工作台（單一檔案版）

用途：讓多個「OpenAI Chat Completions 相容」的 AI 服務協作——
      平行回答、主持 AI 彙整、匿名互評修正、接力精修、分工合作、延續對話。
Agent：模型自己決定讀檔、改檔、執行指令、查網路（工具＋權限＋代理迴圈），修改前自動備份、可復原。
執行：python AI協作.py              （只用 Python 內建模組，需要 Python 3.10 以上）
      python AI協作.py --selftest   （用內建的模擬服務自我測試，不連網）

檔案結構（全部在這一個檔案內，依區段排列）：
  1. 常數、路徑、角色、主題     2. 金鑰與環境變數     3. API 連線
  4. 協作流程                   5. 設定檔與紀錄       6. 協作拓樸圖
  7. 主視窗                     8. 自我測試與進入點
"""

import hashlib
import base64
import json
import logging
import math
import os
import queue
import random
import re
import shutil
import subprocess
import stat
import tempfile
import difflib
import datetime as _dt
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# tkinter 延後到需要畫面時才載入，讓 --selftest 在沒有視窗環境的電腦也能跑核心測試
tk = ttk = tkfont = filedialog = messagebox = simpledialog = colorchooser = None


def _load_tk():
    global tk, ttk, tkfont, filedialog, messagebox, simpledialog, colorchooser
    import tkinter as _tk
    from tkinter import colorchooser as _cc, filedialog as _fd, font as _font, messagebox as _mb, \
        simpledialog as _sd, ttk as _ttk
    tk, ttk, tkfont, filedialog, messagebox, simpledialog, colorchooser = _tk, _ttk, _font, _fd, _mb, _sd, _cc


