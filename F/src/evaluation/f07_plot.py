"""
F07 散點圖：每次提問耗時 vs 正確率（十種設定）

【做什麼】
  讀 f07_cost.py 輸出的 f07_per_query.csv，畫上下兩張散點圖（同一個 y 軸刻度）：
    上：每次提問合計耗時（檢索＋選材＋回答）vs 正確率
    下：只看選材耗時（隨方法而變的部分）vs 正確率
  藍點 K0、橘點 K1；灰色箭頭連接同一策略的 K0 → K1。
  只用 Python 標準庫，直接輸出 SVG（瀏覽器可開、可插入報告；不需 matplotlib）。

【用法】
  .venv/bin/python src/evaluation/f07_plot.py --per-query f07/f07_per_query.csv --out f07/f07_cost_vs_accuracy.svg
"""

import argparse
import csv
from html import escape

# 預設調色盤的類別色第 1、2 格（藍、橘），淺色底
COLOR = {"K0": "#2a78d6", "K1": "#eb6834"}
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#1f1f1e", "#52514c", "#8a8983", "#e6e5e0"
FONT = "PingFang TC, Hiragino Sans GB, Noto Sans CJK TC, Microsoft JhengHei, sans-serif"
INDEX_NAME = {"K0": "K0 原文索引", "K1": "K1 原文＋事實"}

W, H = 680, 930
LEFT, PANEL_W, PLOT_H = 80, 520, 290
TOPS = [130, 530]
Y_MIN, Y_MAX = 0.28, 0.56

# 標籤位置的個別調整：(面板, 設定) → (dx, dy, 對齊, [改寫文字]) 或 "hide"
LABEL_OVERRIDE = {
    ("total", "K1-C"): (-10, 4, "end"),
    ("total", "K0-C"): (10, 4, "start"),
    ("total", "K0-Q"): (0, 22, "middle"),
    ("sel", "K0-C"): "hide",
    ("sel", "K1-C"): (10, 4, "start", "K0-C／K1-C（重疊）"),
}


def arrow(x1, y1, x2, y2, head=9):
    """線段＋實心三角箭頭（不用 SVG marker，轉成 PNG 時也能正確顯示）。"""
    d = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    ux, uy = (x2 - x1) / d, (y2 - y1) / d
    bx, by = x2 - ux * head, y2 - uy * head
    px, py = -uy * head * 0.45, ux * head * 0.45
    return [f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{bx:.1f}" y2="{by:.1f}" stroke="{MUTED}" stroke-width="1.5"/>',
            f'<polygon points="{x2:.1f},{y2:.1f} {bx + px:.1f},{by + py:.1f} {bx - px:.1f},{by - py:.1f}" '
            f'fill="{MUTED}"/>']


def nice_ticks(lo, hi, step):
    t, out = round(lo / step) * step, []
    while t <= hi + 1e-9:
        if t >= lo - 1e-9:
            out.append(round(t, 6))
        t += step
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--per-query", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    rows = list(csv.DictReader(open(a.per_query, encoding="utf-8-sig")))
    pts = [{"i": r["索引"], "s": r["策略"], "acc": float(r["正確率(F04)"]),
            "total": float(r["每次提問合計(秒)"]), "sel": float(r["選材(秒，CPU)"])} for r in rows]

    panels = [
        ("total", "每次提問合計耗時（秒）", "檢索＋選材＋回答", 9.0, 12.6, 0.5),
        ("sel", "選材耗時（秒）", "只看隨方法而變的部分（CPU）", 0.0, 2.6, 0.5),
    ]
    yt = nice_ticks(Y_MIN, Y_MAX, 0.05)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="{FONT}">',
         f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
         f'<text x="24" y="34" font-size="20" font-weight="600" fill="{INK}">'
         '十種設定的成本與正確率（g02-v1，80 題）</text>',
         f'<text x="24" y="58" font-size="13" fill="{INK2}">越靠左上越划算：耗時少、正確率高。</text>',
         f'<text x="24" y="78" font-size="13" fill="{INK2}">灰色箭頭＝同一選材策略從 K0 換成 K1。</text>']

    left = LEFT
    for (key, xlabel, sub, x0, x1, step), TOP in zip(panels, TOPS):
        sx = lambda v, x0=x0, x1=x1: left + (v - x0) / (x1 - x0) * PANEL_W
        sy = lambda v, TOP=TOP: TOP + PLOT_H - (v - Y_MIN) / (Y_MAX - Y_MIN) * PLOT_H
        o.append(f'<text x="{left}" y="{TOP - 12}" font-size="14" font-weight="600" fill="{INK}">{xlabel}'
                 f'<tspan font-size="12" font-weight="400" fill="{INK2}">　{sub}</tspan></text>')
        for v in yt:
            o.append(f'<line x1="{left}" x2="{left + PANEL_W}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
            o.append(f'<text x="{left - 8}" y="{sy(v) + 4:.1f}" font-size="11" fill="{MUTED}" '
                     f'text-anchor="end">{v:.2f}</text>')
        for v in nice_ticks(x0, x1, step):
            o.append(f'<line x1="{sx(v):.1f}" x2="{sx(v):.1f}" y1="{TOP + PLOT_H}" y2="{TOP + PLOT_H + 4}" '
                     f'stroke="{MUTED}"/>')
            o.append(f'<text x="{sx(v):.1f}" y="{TOP + PLOT_H + 18}" font-size="11" fill="{MUTED}" '
                     f'text-anchor="middle">{v:g}</text>')
        o.append(f'<line x1="{left}" x2="{left + PANEL_W}" y1="{TOP + PLOT_H}" y2="{TOP + PLOT_H}" '
                 f'stroke="{MUTED}" stroke-width="1"/>')
        o.append(f'<text x="{left - 46}" y="{TOP + PLOT_H / 2}" font-size="12" fill="{INK2}" '
                 f'text-anchor="middle" transform="rotate(-90 {left - 46} {TOP + PLOT_H / 2})">正確率</text>')

        # 箭頭 K0 → K1（太短就不畫）
        for s in ["R", "MMR", "C", "Q", "FL"]:
            p0 = next(q for q in pts if q["i"] == "K0" and q["s"] == s)
            p1 = next(q for q in pts if q["i"] == "K1" and q["s"] == s)
            ax, ay, bx, by = sx(p0[key]), sy(p0["acc"]), sx(p1[key]), sy(p1["acc"])
            d = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
            if d < 22:
                continue
            ux, uy = (bx - ax) / d, (by - ay) / d
            o.extend(arrow(ax + ux * 9, ay + uy * 9, bx - ux * 10, by - uy * 10))

        # 點與標籤：預設 K0 標在左、K1 標在右；擠在一起的幾個點個別調整（看過成圖後設定）
        for q in pts:
            x, y = sx(q[key]), sy(q["acc"])
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{COLOR[q["i"]]}" stroke="{SURFACE}" '
                     f'stroke-width="2"><title>{q["i"]}-{q["s"]}：正確率 {q["acc"]:.3f}，'
                     f'每次提問 {q["total"]:.2f} 秒，選材 {q["sel"]:.2f} 秒</title></circle>')
        for q in pts:
            x, y = sx(q[key]), sy(q["acc"])
            name = q["i"] + "-" + q["s"]
            right = q["i"] == "K1"
            dx, dy, anchor = (10, 4, "start") if right else (-10, 4, "end")
            pos = LABEL_OVERRIDE.get((key, name))
            if pos == "hide":
                continue
            if isinstance(pos, tuple):
                dx, dy, anchor, name = pos[0], pos[1], pos[2], pos[3] if len(pos) > 3 else name
            o.append(f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" font-size="12" fill="{INK}" '
                     f'text-anchor="{anchor}">{escape(name)}</text>')

    # 圖例
    lx, ly = 24, TOPS[-1] + PLOT_H + 56
    for n, idx in enumerate(["K0", "K1"]):
        x = lx + n * 170
        o.append(f'<circle cx="{x + 6}" cy="{ly - 4}" r="6" fill="{COLOR[idx]}"/>')
        o.append(f'<text x="{x + 18}" y="{ly}" font-size="12" fill="{INK}">{INDEX_NAME[idx]}</text>')
    x = lx + 330
    o.extend(arrow(x, ly - 4, x + 28, ly - 4))
    o.append(f'<text x="{x + 34}" y="{ly}" font-size="12" fill="{INK}">同策略 K0 → K1</text>')
    o.append(f'<text x="{lx}" y="{ly + 28}" font-size="11" fill="{INK2}">正確率為 F04 judge 分數（80 題，一題＝1.25 個百分點）；'
             '差值的 95% 信賴區間見 F06，多數包含 0。</text>')
    o.append(f'<text x="{lx}" y="{ly + 46}" font-size="11" fill="{INK2}">回答在 A40／L40S、選材在 CPU，秒數口徑見 F/F07/README.md。</text>')
    o.append("</svg>")
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(o))
    print(f"輸出：{a.out}")


if __name__ == "__main__":
    main()
