#!/usr/bin/env python3
"""Generate ELI5-style repo map SVGs (zh + en) for kxy README."""

CARDS = [
    # (dir, icon-letter, color, border, zh_title, zh_desc, en_title, en_desc)
    ("frontend/", "F", "#E8F0FE", "#4285F4",
     "点餐台", "React + XYFlow 画布：拖节点、连线、看结果",
     "Dining room", "React + XYFlow canvas: drag nodes, connect, view results"),
    ("backend/", "B", "#E6F4EA", "#34A853",
     "厨房", "FastAPI：管文件、Skill 快照、运行流程与产物",
     "Kitchen", "FastAPI: files, Skill snapshots, runs and artifacts"),
    ("vendor/skillhub/", "V", "#FEF7E0", "#F9AB00",
     "外购引擎", "固定版本的 MIT 上游，只经受限桥接调用",
     "Bought-in engine", "Pinned MIT upstream, used via bounded bridges only"),
    ("acceptance/", "A", "#F3E8FD", "#A142F4",
     "质检报告", "每个版本功能的自动化验收证据（含日志）",
     "QC reports", "Automated acceptance evidence for every version"),
    ("docs/", "D", "#F1F3F4", "#9AA0A6",
     "设计图纸", "实现与升级方案笔记",
     "Blueprints", "Design and upgrade plan notes"),
    ("branding/", "L", "#FCE8E6", "#EA4335",
     "店招", "可替换的 logo（png / webp / svg）",
     "Shop sign", "Swappable logo (png / webp / svg)"),
    ("setup.sh · start.sh", "S", "#E0F7FA", "#00ACC1",
     "开店按钮", "一键安装依赖 / 启动本机服务（另有 .command 双击版）",
     "Open-for-business buttons", "One-shot install / launch (also .command double-click versions)"),
    ("data/", "P", "#FFF8E1", "#F9AB00",
     "食材储藏室", "运行数据：只留在你的机器上，不进仓库",
     "Pantry", "Runtime data: stays on your machine, not in the repo"),
]

TITLE = {
    "zh": ("kxy 仓库地图 · ELI5 版", "把它想象成一家「本机研究餐厅」——你在点餐台操作，厨房干活，质检报告保证每道菜合格"),
    "en": ("kxy repo map, ELI5 edition", "Think of it as a local research restaurant: you order at the counter, the kitchen cooks, QC reports vouch for every dish"),
}

FOOTER = {
    "zh": ("不在仓库里（本地生成）：data/ · .venv/ · node_modules/ · frontend/dist* —— 首次运行 setup.sh 时现场搭建",),
    "en": ("Not in the repo (generated locally): data/ · .venv/ · node_modules/ · frontend/dist* — built by setup.sh on first run",),
}


def render(lang: str) -> str:
    W, H = 680, 620
    PAD = 20
    CARD_W, CARD_H = 308, 96
    GAP_X, GAP_Y = 24, 16
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'font-family="-apple-system, \'PingFang SC\', \'Helvetica Neue\', Arial, sans-serif">',
        f'<rect width="{W}" height="{H}" rx="16" fill="#FFFFFF" stroke="#DADCE0"/>',
    ]
    t_title, t_sub = TITLE[lang]
    parts.append(f'<text x="{PAD+6}" y="42" font-size="19" font-weight="700" fill="#202124">{t_title}</text>')
    parts.append(f'<text x="{PAD+6}" y="64" font-size="12" fill="#5F6368">{t_sub}</text>')

    y0 = 86
    for i, c in enumerate(CARDS):
        col, row = i % 2, i // 2
        x = PAD + col * (CARD_W + GAP_X)
        y = y0 + row * (CARD_H + GAP_Y)
        dirname, letter, fill, border, zh_t, zh_d, en_t, en_d = c
        title, desc = (zh_t, zh_d) if lang == "zh" else (en_t, en_d)
        dashed = ' stroke-dasharray="5,3"' if dirname == "data/" else ""
        parts.append(
            f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="10" '
            f'fill="{fill}" stroke="{border}"{dashed}/>'
        )
        # icon
        ix, iy = x + 12, y + 12
        parts.append(f'<rect x="{ix}" y="{iy}" width="24" height="24" rx="6" fill="{border}"/>')
        parts.append(
            f'<text x="{ix+12}" y="{iy+17}" font-size="13" font-weight="700" fill="#FFFFFF" '
            f'text-anchor="middle">{letter}</text>'
        )
        # dir name + metaphor title
        parts.append(
            f'<text x="{ix+34}" y="{iy+11}" font-size="12.5" font-weight="700" '
            f'fill="#202124" font-family="Menlo, Consolas, monospace">{dirname}</text>'
        )
        parts.append(
            f'<text x="{ix+34}" y="{iy+26}" font-size="12.5" font-weight="600" fill="#202124">{title}</text>'
        )
        # desc (wrap into two lines)
        words = desc.split(" ")
        mid = len(words) // 2
        line1, line2 = " ".join(words[:mid]), " ".join(words[mid:])
        dy = y + 66
        parts.append(f'<text x="{x+14}" y="{dy}" font-size="11" fill="#3C4043">{line1}</text>')
        if line2.strip():
            parts.append(f'<text x="{x+14}" y="{dy+15}" font-size="11" fill="#3C4043">{line2}</text>')

    fy = y0 + 4 * (CARD_H + GAP_Y) + 6
    ftext = FOOTER[lang][0]
    parts.append(f'<rect x="{PAD}" y="{fy}" width="{W-2*PAD}" height="34" rx="8" fill="#F8F9FA" stroke="#DADCE0"/>')
    parts.append(f'<text x="{PAD+12}" y="{fy+21}" font-size="11" fill="#5F6368">{ftext}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    import pathlib
    out = pathlib.Path(__file__).resolve().parent
    (out / "eli5-repo-map.svg").write_text(render("zh"), encoding="utf-8")
    (out / "eli5-repo-map-en.svg").write_text(render("en"), encoding="utf-8")
    print("written:", out / "eli5-repo-map.svg", "and eli5-repo-map-en.svg")
