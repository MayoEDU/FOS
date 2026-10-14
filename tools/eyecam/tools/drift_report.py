"""eyecam のドリフトの記録（`driftlog on`、または `eyecam-rec --replay … --driftlog FILE` の CSV）をまとめる。

    python3 drift_report.py drift_2026-10-12_10-00-00.csv            # 5 分ごと
    python3 drift_report.py drift_….csv --bucket 60                    # 1 分ごと

目ごと・かぶりごと（`wear`）に、かぶってからの時間（`wear_s`）で区切って、瞳が見つかった割合・瞳の位置（中央値）・
探す枠の左端 x_min・開いた目の箱の明るさ box_open・Valve が 0.6 以上のときに閉じたと出した割合・基準線
（開き ap_n と皮膚の線）を出す。そのあと、かぶりごとに最初と最後の区切りを比べて、ずれた値に印を付ける。
標準ライブラリだけで動く。
"""

import argparse
import csv
import statistics
import sys

# 最初と最後の区切りを比べて印を付けるしきい値
CX_MOVE_PX = 8.0  # 瞳の位置が動いた
FOUND_DROP = 0.15  # 瞳が見つかる割合が下がった（0〜1）
CLOSED_RISE = 0.05  # Valve は開いているのに閉じたと出す割合が増えた（0〜1）
REF_CHANGE = 0.10  # box_open・ap_n が変わった（割合）
EDGE_GAP_PX = 16.0  # 瞳の耳側の縁が x_min からこれより近い（eyecam の EDGE_LOST_PX）
VALVE_OPEN = 0.6  # 「Valve が開いていると言っている」


def num(v):
    """CSV のセルを数に（空なら None）。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def med(values):
    """None を除いた中央値（何もなければ None）。"""
    v = [x for x in values if x is not None]
    return statistics.median(v) if v else None


def weighted(rows, col, pick=lambda r: True):
    """フレーム数で重みを付けた平均（割合の列用）。対象のフレームがなければ None。"""
    n = s = 0.0
    for r in rows:
        if not pick(r):
            continue
        f, v = num(r['frames']), num(r[col])
        if f and v is not None:
            n += f
            s += f * v
    return s / n if n else None


def summarize(rows):
    """1 つの区切りの行から、出す値をまとめる。"""
    last = rows[-1]
    gaps = []
    for r in rows:
        cx, pr, xm = num(r['pupil_cx']), num(r['pupil_r']), num(r['x_min'])
        if None not in (cx, pr, xm):
            gaps.append(cx - pr - xm)
    return {
        'from_s': num(rows[0]['wear_s']),
        'to_s': num(last['wear_s']),
        'frames': sum(num(r['frames']) or 0 for r in rows),
        'found': weighted(rows, 'pupil_share'),
        'cx': med(num(r['pupil_cx']) for r in rows),
        'cy': med(num(r['pupil_cy']) for r in rows),
        'edge_gap': med(gaps),
        'x_min': num(last['x_min']),
        'x_min_src': last['x_min_src'],
        'x_min_set_s': num(last['x_min_set_s']),
        'box_open': med(num(r['box_open']) for r in rows),
        'closed_open': weighted(rows, 'closed_share', lambda r: (num(r['valve_open']) or 0) >= VALVE_OPEN),
        'edge_held': weighted(rows, 'edge_held_share'),
        'ap_n': med(num(r['base_ap_px']) for r in rows),
        'skin': med(num(r['base_skin_px']) for r in rows),
        'ready': last['ready'] == '1',
    }


def fmt(v, spec):
    return '-' if v is None else format(v, spec)


def flags(first, last):
    """最初と最後の区切りの差から、ずれた値の説明を返す。"""
    out = []

    def moved(key, limit, label):
        a, b = first[key], last[key]
        if a is not None and b is not None and abs(b - a) > limit:
            out.append(f'{label} {a:.1f} -> {b:.1f} px（{b - a:+.1f}）')

    moved('cx', CX_MOVE_PX, '瞳の x が動いた')
    moved('cy', CX_MOVE_PX, '瞳の y が動いた')
    a, b = first['found'], last['found']
    if a is not None and b is not None and a - b > FOUND_DROP:
        out.append(f'瞳が見つかる割合が下がった {a:.0%} -> {b:.0%}')
    a, b = first['closed_open'], last['closed_open']
    if a is not None and b is not None and b - a > CLOSED_RISE:
        out.append(f'Valve が開いているのに閉じたと出す割合が増えた {a:.1%} -> {b:.1%}')
    for key, label in (('box_open', 'box_open'), ('ap_n', '開きの基準線 ap_n')):
        a, b = first[key], last[key]
        if a and b is not None and abs(b - a) / a > REF_CHANGE:
            out.append(f'{label} が変わった {a:.1f} -> {b:.1f}（{(b - a) / a:+.0%}）')
    if last['edge_gap'] is not None and last['edge_gap'] < EDGE_GAP_PX:
        out.append(f'瞳の耳側の縁が x_min（{last["x_min_src"]}、{fmt(last["x_min_set_s"], ".0f")} 秒で決まった）から '
                   f'{last["edge_gap"]:.1f} px（{EDGE_GAP_PX:.0f} px 未満）')
    return out


def main():
    ap = argparse.ArgumentParser(description='eyecam のドリフトの記録（CSV）をまとめる')
    ap.add_argument('csv', help='drift_*.csv')
    ap.add_argument('--bucket', type=float, default=300.0, help='区切りの長さ（秒、既定 300 = 5 分）')
    args = ap.parse_args()

    with open(args.csv, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f'{args.csv}: 行がない')

    # (目, かぶり, 区切り) ごとに分ける。かぶってからの時間がない行（かぶり始めの前）は飛ばす
    groups = {}
    for r in rows:
        ws = num(r['wear_s'])
        if ws is None:
            continue
        key = (r['eye'], int(r['wear']), int(ws // args.bucket))
        groups.setdefault(key, []).append(r)

    print(f'{args.csv}: {len(rows)} 行、区切り {args.bucket:.0f} 秒')
    head = (f'{"かぶり":>4} {"時間(s)":>11} {"frames":>7} {"瞳":>5} {"cx":>6} {"cy":>6} {"縁-x_min":>8} {"x_min":>5} '
            f'{"box_open":>8} {"閉/V開":>6} {"端保持":>6} {"ap_n":>6} {"皮膚":>6}')
    for eye in ('L', 'R'):
        keys = sorted(k for k in groups if k[0] == eye)
        if not keys:
            continue
        print(f'\n[{"左目" if eye == "L" else "右目"} {eye}]')
        print(head)
        per_wear = {}
        for k in keys:
            s = summarize(groups[k])
            per_wear.setdefault(k[1], []).append(s)
            print(f'{k[1]:>4} {fmt(s["from_s"], ".0f"):>5}-{fmt(s["to_s"], ".0f"):<5} {s["frames"]:>7.0f} '
                  f'{fmt(s["found"], ".0%"):>5} {fmt(s["cx"], ".1f"):>6} {fmt(s["cy"], ".1f"):>6} '
                  f'{fmt(s["edge_gap"], ".1f"):>8} {fmt(s["x_min"], ".0f"):>5} {fmt(s["box_open"], ".1f"):>8} '
                  f'{fmt(s["closed_open"], ".1%"):>6} {fmt(s["edge_held"], ".1%"):>6} {fmt(s["ap_n"], ".1f"):>6} '
                  f'{fmt(s["skin"], ".1f"):>6}' + ('' if s['ready'] else '  (基準線を覚えている途中)'))
        for wear, ss in per_wear.items():
            # 半分に満たない区切り（終わりの端など）は比べない
            full = max(s['frames'] for s in ss)
            ss = [s for s in ss if s['frames'] >= 0.5 * full]
            if len(ss) < 2:
                print(f'  かぶり {wear}: 区切りが 1 つだけなので、ずれは比べられない')
                continue
            found = flags(ss[0], ss[-1])
            print(f'  かぶり {wear}（最初と最後の区切り）: ' + ('目立つずれはない' if not found else ''))
            for line in found:
                print(f'    ! {line}')
    print('\n瞳 = 瞳が見つかった割合、縁-x_min = 瞳の耳側の縁（cx - 半径）と枠の左端の差、'
          f'閉/V開 = Valve が {VALVE_OPEN} 以上のフレームで閉じたと出した割合、端保持 = 枠の端で見失って開いたままにした割合、'
          'ap_n・皮膚 = 基準線（px）')


if __name__ == '__main__':
    main()
