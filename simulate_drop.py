import random, math
from app import app, db, Skin, CASE_PRICE

# Настройки (подбирай)
TARGET_MULT = 0.60   # было выше — это и даёт “в плюс”
SIGMA = 0.60         # меньше разброс -> реже дорогие
WINDOW_START = 0.20
WINDOW_STEP = 0.15
WINDOW_MAX = 1.00

def clamp(x, a, b):
    return max(a, min(b, x))

def pick_by_target(cands):
    prices = [s.price for s in cands]
    mn, mx = min(prices), max(prices)

    mu = math.log(CASE_PRICE * TARGET_MULT)
    target = math.exp(random.gauss(mu, SIGMA))
    target = clamp(target, mn, mx)

    w = WINDOW_START
    band = []
    while w <= WINDOW_MAX:
        lo, hi = target*(1-w), target*(1+w)
        band = [s for s in cands if lo <= s.price <= hi]
        if band:
            break
        w += WINDOW_STEP

    if not band:
        # ближайший по цене
        return min(cands, key=lambda s: abs(s.price - target))

    weights = [1.0 / (abs(s.price - target) + 1.0) for s in band]
    return random.choices(band, weights=weights, k=1)[0]

def main():
    with app.app_context():
        cands = Skin.query.filter(Skin.count > 0, Skin.price > 0).all()
        N = 20000
        total = 0
        for _ in range(N):
            s = pick_by_target(cands)
            total += s.price
        avg = total / N
        print("skins:", len(cands))
        print("avg drop:", round(avg, 2), "★")
        print("house edge:", round((CASE_PRICE - avg) / CASE_PRICE * 100, 1), "%")

if __name__ == "__main__":
    main()