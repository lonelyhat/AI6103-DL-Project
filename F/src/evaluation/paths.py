"""
路徑設定：找出「程式根目錄」和「組內專案根目錄」

【為什麼需要這個檔案】
  同一份程式會放在兩個地方執行：
    1. 本機：/Users/.../DL Final Project/src/evaluation/
             組內專案另外下載在 /Users/.../DL Final Project/AI6103-DL-Project-main_V2/
    2. 組內 GitHub 的 F_Evaluation 分支：<repo>/F/src/evaluation/
             組內專案就是 <repo> 本身
  兩種情況下，A01、A02 的位置不同。這裡統一判斷，其他程式只要 import 這個檔案即可，
  以後換資料夾（例如 V3）只要改這裡的一行。

【判斷順序】
  1. 若有設定環境變數 TEAM_REPO，就用它（臨時指定用）
  2. 若程式本身位在組內專案裡（往上找得到「A-数据线」資料夾），就用那一層
  3. 否則使用本機預設的下載資料夾 LOCAL_TEAM_FOLDER
"""

import os
from pathlib import Path

# 本機下載的組內專案資料夾名稱（換新版時只要改這一行）
LOCAL_TEAM_FOLDER = "AI6103-DL-Project-main_V2"

# 程式根目錄：本檔在 <程式根目錄>/src/evaluation/paths.py，往上兩層
#   本機 → DL Final Project/；組內 repo → <repo>/F/
CODE_ROOT = Path(__file__).resolve().parents[2]


def find_team_root():
    """依上面的判斷順序，回傳組內專案根目錄。"""
    env = os.environ.get("TEAM_REPO")
    if env:
        return Path(env).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "A-数据线").is_dir():
            return parent
    return CODE_ROOT / LOCAL_TEAM_FOLDER


TEAM_ROOT = find_team_root()
A_LINE = TEAM_ROOT / "A-数据线"
A01_OUTPUT = A_LINE / "A01" / "output"   # A01 交接資料（題目、評價檔、輪映射）
A02_DIR = A_LINE / "A02"                  # A02 證據指標程式


if __name__ == "__main__":
    # 直接執行本檔可確認目前抓到的路徑：.venv/bin/python src/evaluation/paths.py
    print(f"程式根目錄：{CODE_ROOT}")
    print(f"組內專案：  {TEAM_ROOT}（存在：{TEAM_ROOT.is_dir()}）")
    print(f"A01 輸出：  {A01_OUTPUT}（存在：{A01_OUTPUT.is_dir()}）")
    print(f"A02 程式：  {A02_DIR}（存在：{A02_DIR.is_dir()}）")
