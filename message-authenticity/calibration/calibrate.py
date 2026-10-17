"""Thresholds from scores: tuned on one half of the set, measured on the other (so the numbers are not flattered)."""
import json, math, random, sys
random.seed(2026)
scores = json.load(open(sys.argv[1]))[sys.argv[2]]
def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)); return (max(0, (c - a) / d), (c + a) / d)
out = {}
for lang in ('en', 'fr'):
    h = scores[lang]['human'][:]; g = scores[lang]['generated'][:]
    random.shuffle(h); random.shuffle(g)
    th, eh = h[:len(h)//2], h[len(h)//2:]; tg, eg = g[:len(g)//2], g[len(g)//2:]
    # HIGH: just above the highest human of the tuning half; MID: the 95th percentile of the tuning humans
    high = max(th) + 1e-6; mid = sorted(th)[int(0.95 * len(th))]
    res = {'high': round(high, 4), 'mid': round(mid, 4), 'n_tune_human': len(th), 'n_test_human': len(eh), 'n_test_generated': len(eg)}
    for name, t in (('mid', mid), ('high', high)):
        fp = sum(x >= t for x in eh); tp = sum(x >= t for x in eg)
        lo, hi = wilson(fp, len(eh)); tlo, thi = wilson(tp, len(eg))
        res[name + '_test'] = {'false_positive': f'{fp}/{len(eh)}', 'fpr_95ci_pct': [round(lo * 100, 1), round(hi * 100, 1)], 'true_positive': f'{tp}/{len(eg)}', 'tpr_95ci_pct': [round(tlo * 100, 1), round(thi * 100, 1)]}
    out[lang] = res
print(json.dumps(out, indent=1))
json.dump(out, open('calibration.json', 'w'), indent=1)
