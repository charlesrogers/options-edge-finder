"""
Bayesian Signal Model (Proposal 3A — lightweight implementation)

Replaces the static point-scoring system (calc_vrp_signal) with a
logistic regression trained on scored predictions. Outputs calibrated
probabilities instead of arbitrary point totals.

Uses scipy (already a dependency) instead of pymc to avoid heavy
MCMC dependencies. Achieves similar results via:
  1. L2-regularized logistic regression (equivalent to Normal prior)
  2. Bootstrap resampling for posterior uncertainty (credible intervals)

From Sinclair & Mack (2024): "Every trade contains an implicit forecast."
This makes the forecast explicit and calibrated.

From LEARN_TEST_TRADE_SPEC H10 pass thresholds:
  - Calibration error < 5%
  - CLV uplift > 0.5% vs static
  - OOS log-likelihood improves > 5%
"""

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit  # sigmoid function


# ============================================================
# FEATURE ENGINEERING
# ============================================================

def prepare_features(predictions_df):
    """
    Convert raw prediction data into standardized features for the model.

    Args:
        predictions_df: DataFrame with columns from predictions table

    Returns:
        X: (n, k) array of standardized features
        y: (n,) array of seller_won outcomes (0/1)
        feature_names: list of feature names
        scalers: dict of {feature: (mean, std)} for standardization
    """
    df = predictions_df.copy()
    required = ["seller_won", "vrp", "iv_rank"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Drop rows with missing outcome or key features
    df = df.dropna(subset=["seller_won", "vrp"])

    feature_cols = []
    features = {}

    # VRP (continuous)
    if "vrp" in df.columns:
        features["vrp"] = df["vrp"].fillna(0).values
        feature_cols.append("vrp")

    # IV Rank (continuous, 0-100)
    if "iv_rank" in df.columns:
        features["iv_rank"] = df["iv_rank"].fillna(50).values
        feature_cols.append("iv_rank")

    # IV Percentile
    if "iv_pctl" in df.columns and df["iv_pctl"].notna().any():
        features["iv_pctl"] = df["iv_pctl"].fillna(50).values
        feature_cols.append("iv_pctl")

    # Term structure (categorical → numeric)
    if "term_label" in df.columns:
        term_map = {"contango": 1, "Contango": 1, "flat": 0, "Flat": 0,
                     "backwardation": -1, "Backwardation": -1, "N/A": 0}
        features["term_numeric"] = df["term_label"].map(term_map).fillna(0).values
        feature_cols.append("term_numeric")

    # Regime (categorical → numeric)
    if "regime" in df.columns:
        regime_map = {"low_vol": 0, "Low Vol": 0, "normal": 1, "Normal": 1,
                       "high_vol": 2, "High Vol": 2, "elevated": 2, "Elevated": 2,
                       "crisis": 3, "Crisis": 3, "crash": 3, "Crash": 3}
        features["regime_numeric"] = df["regime"].map(regime_map).fillna(1).values
        feature_cols.append("regime_numeric")

    # Skew
    if "skew" in df.columns and df["skew"].notna().any():
        features["skew"] = df["skew"].fillna(0).values
        feature_cols.append("skew")

    # FOMC proximity
    if "fomc_days" in df.columns and df["fomc_days"].notna().any():
        features["fomc_near"] = (df["fomc_days"].fillna(30) <= 5).astype(float).values
        feature_cols.append("fomc_near")

    # Build X matrix
    X_raw = np.column_stack([features[col] for col in feature_cols])
    y = df["seller_won"].values.astype(float)

    # Standardize (z-score)
    scalers = {}
    X = np.zeros_like(X_raw)
    for i, col in enumerate(feature_cols):
        mean = X_raw[:, i].mean()
        std = X_raw[:, i].std()
        if std < 1e-10:
            std = 1.0
        X[:, i] = (X_raw[:, i] - mean) / std
        scalers[col] = (float(mean), float(std))

    return X, y, feature_cols, scalers


# ============================================================
# LOGISTIC REGRESSION WITH L2 REGULARIZATION
# ============================================================

def _log_likelihood(params, X, y, l2_lambda=1.0):
    """Negative log-likelihood with L2 penalty (equivalent to Normal prior)."""
    intercept = params[0]
    betas = params[1:]
    logits = intercept + X @ betas
    probs = expit(logits)

    # Clip to avoid log(0)
    probs = np.clip(probs, 1e-10, 1 - 1e-10)

    ll = np.sum(y * np.log(probs) + (1 - y) * np.log(1 - probs))

    # L2 penalty (Normal prior with sigma = 1/sqrt(lambda))
    penalty = l2_lambda * np.sum(betas ** 2) / 2

    return -(ll - penalty)


def fit_model(X, y, l2_lambda=1.0):
    """
    Fit L2-regularized logistic regression.

    Args:
        X: (n, k) standardized feature matrix
        y: (n,) binary outcomes
        l2_lambda: Regularization strength (1.0 = weakly informative prior)

    Returns:
        params: array [intercept, beta1, beta2, ...]
    """
    n_features = X.shape[1]
    x0 = np.zeros(1 + n_features)

    result = minimize(
        _log_likelihood, x0, args=(X, y, l2_lambda),
        method='L-BFGS-B',
        options={'maxiter': 1000, 'ftol': 1e-10},
    )

    return result.x


def predict_proba(X, params):
    """Predict P(seller_wins) from features and fitted params."""
    intercept = params[0]
    betas = params[1:]
    logits = intercept + X @ betas
    return expit(logits)


# ============================================================
# BOOTSTRAP UNCERTAINTY (approximate Bayesian posterior)
# ============================================================

def fit_with_uncertainty(X, y, n_bootstrap=200, l2_lambda=1.0):
    """
    Fit model with bootstrap resampling for uncertainty estimation.

    Returns:
        params_mean: Mean parameter estimates
        params_samples: (n_bootstrap, n_params) array of bootstrap samples
        feature_names_map: Not returned here — caller provides
    """
    n = len(y)
    all_params = []

    # Full-data fit
    params_full = fit_model(X, y, l2_lambda)

    # Bootstrap
    for _ in range(n_bootstrap):
        idx = np.random.choice(n, size=n, replace=True)
        X_boot = X[idx]
        y_boot = y[idx]
        try:
            params_boot = fit_model(X_boot, y_boot, l2_lambda)
            all_params.append(params_boot)
        except Exception:
            continue

    if not all_params:
        return params_full, np.array([params_full])

    params_samples = np.array(all_params)
    return params_full, params_samples


# ============================================================
# FULL BAYESIAN SIGNAL MODEL
# ============================================================

class BayesianSignalModel:
    """
    Trained model that produces calibrated probability signals.

    Usage:
        model = BayesianSignalModel()
        model.train(scored_predictions_df)
        signal = model.predict(vrp=5.2, iv_rank=65, term_label="contango", ...)
    """

    def __init__(self):
        self.params = None
        self.params_samples = None
        self.feature_names = None
        self.scalers = None
        self.n_train = 0
        self.is_trained = False

    def train(self, predictions_df, n_bootstrap=200, l2_lambda=1.0):
        """Train on scored predictions."""
        X, y, feature_names, scalers = prepare_features(predictions_df)

        if len(X) < 30:
            print(f"[bayesian] Only {len(X)} observations — too few to train reliably")
            return False

        self.params, self.params_samples = fit_with_uncertainty(X, y, n_bootstrap, l2_lambda)
        self.feature_names = feature_names
        self.scalers = scalers
        self.n_train = len(X)
        self.is_trained = True

        print(f"[bayesian] Trained on {len(X)} predictions, {len(self.feature_names)} features")
        self._print_coefficients()
        return True

    def _print_coefficients(self):
        """Print coefficient summary (like Bayesian posterior)."""
        if not self.is_trained:
            return
        names = ["intercept"] + self.feature_names
        for i, name in enumerate(names):
            mean = self.params[i]
            if self.params_samples is not None and len(self.params_samples) > 1:
                ci_lo = np.percentile(self.params_samples[:, i], 5)
                ci_hi = np.percentile(self.params_samples[:, i], 95)
                print(f"  {name:20s}: {mean:+.4f}  (90% CI: [{ci_lo:+.4f}, {ci_hi:+.4f}])")
            else:
                print(f"  {name:20s}: {mean:+.4f}")

    def predict(self, **kwargs):
        """
        Generate Bayesian signal for a single observation.

        Args (keyword):
            vrp, iv_rank, iv_pctl, term_label, regime, skew, fomc_days

        Returns:
            dict with prob_seller_wins, ci_lower, ci_upper, signal, confidence, top_driver
        """
        if not self.is_trained:
            return {"error": "Model not trained"}

        # Build feature vector
        raw = {}
        for feat in self.feature_names:
            if feat == "term_numeric":
                term_map = {"contango": 1, "Contango": 1, "flat": 0, "Flat": 0,
                             "backwardation": -1, "Backwardation": -1, "N/A": 0}
                raw[feat] = term_map.get(kwargs.get("term_label", "N/A"), 0)
            elif feat == "regime_numeric":
                regime_map = {"low_vol": 0, "normal": 1, "high_vol": 2, "crisis": 3,
                               "Low Vol": 0, "Normal": 1, "High Vol": 2, "Crisis": 3}
                raw[feat] = regime_map.get(kwargs.get("regime", "normal"), 1)
            elif feat == "fomc_near":
                raw[feat] = 1.0 if kwargs.get("fomc_days", 30) <= 5 else 0.0
            else:
                raw[feat] = kwargs.get(feat, 0)

        # Standardize
        x = np.zeros(len(self.feature_names))
        for i, feat in enumerate(self.feature_names):
            mean, std = self.scalers[feat]
            x[i] = (raw[feat] - mean) / std

        x = x.reshape(1, -1)

        # Point estimate
        prob = float(predict_proba(x, self.params)[0])

        # Bootstrap uncertainty
        if self.params_samples is not None and len(self.params_samples) > 1:
            probs_boot = np.array([
                float(predict_proba(x, p)[0]) for p in self.params_samples
            ])
            ci_lo = float(np.percentile(probs_boot, 5))
            ci_hi = float(np.percentile(probs_boot, 95))
        else:
            ci_lo, ci_hi = prob - 0.1, prob + 0.1

        # Backward-compatible signal
        if prob > 0.70:
            signal = "GREEN"
        elif prob > 0.55:
            signal = "YELLOW"
        else:
            signal = "RED"

        # Confidence from CI width
        ci_width = ci_hi - ci_lo
        confidence = "high" if ci_width < 0.15 else "medium" if ci_width < 0.25 else "low"

        # Top driver
        contributions = []
        betas = self.params[1:]
        for i, feat in enumerate(self.feature_names):
            mean, std = self.scalers[feat]
            contrib = betas[i] * (raw[feat] - mean) / std
            contributions.append((feat, float(contrib)))
        contributions.sort(key=lambda x: abs(x[1]), reverse=True)
        top_driver = f"{contributions[0][0]} ({contributions[0][1]:+.3f})" if contributions else "none"

        return {
            "prob_seller_wins": round(prob, 4),
            "prob_ci_lower": round(ci_lo, 4),
            "prob_ci_upper": round(ci_hi, 4),
            "signal": signal,
            "confidence": confidence,
            "top_driver": top_driver,
            "n_train": self.n_train,
        }

    def calibration_check(self, predictions_df, n_bins=10):
        """
        Check if predicted probabilities match actual win rates.

        Returns:
            dict with calibration_error, bin_details
        """
        if not self.is_trained:
            return {"error": "Model not trained"}

        X, y, _, _ = prepare_features(predictions_df)
        probs = predict_proba(X, self.params)

        # Bin predictions and compare predicted vs actual
        bins = np.linspace(0, 1, n_bins + 1)
        bin_details = []
        errors = []

        for i in range(n_bins):
            mask = (probs >= bins[i]) & (probs < bins[i + 1])
            if mask.sum() < 5:
                continue
            predicted = probs[mask].mean()
            actual = y[mask].mean()
            error = abs(predicted - actual)
            errors.append(error)
            bin_details.append({
                "bin": f"{bins[i]:.1f}-{bins[i+1]:.1f}",
                "n": int(mask.sum()),
                "predicted": round(float(predicted), 4),
                "actual": round(float(actual), 4),
                "error": round(float(error), 4),
            })

        avg_error = float(np.mean(errors)) if errors else 1.0

        return {
            "avg_calibration_error": round(avg_error, 4),
            "passed_h10_calibration": avg_error < 0.05,
            "n_bins_used": len(bin_details),
            "bin_details": bin_details,
        }
