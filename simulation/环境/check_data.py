"""Small environment acceptance check, not a research experiment."""
import json
import platform
from importlib.metadata import version
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

output = Path(__file__).parent / "验收产物"
output.mkdir(exist_ok=True)
x, y = make_classification(n_samples=100, n_features=6, random_state=42)
x_train, x_test, y_train, y_test = train_test_split(x, y, random_state=42)
model = LogisticRegression(max_iter=200).fit(x_train, y_train)
pd.DataFrame(x).to_csv(output / "data-smoke.csv", index=False)
fig, ax = plt.subplots()
ax.scatter(x[:, 0], x[:, 1], c=y)
fig.savefig(output / "data-smoke.png")
plt.close(fig)
result = {"scope": "environment smoke only", "python": platform.python_version(),
          "packages": {name: version(name) for name in
                       ("numpy", "pandas", "matplotlib", "scikit-learn")},
          "test_samples": len(y_test), "score": model.score(x_test, y_test)}
(output / "data-check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
