"""MLflow pyfunc wrapper around the fitted supervised model."""

from __future__ import annotations

import mlflow.pyfunc
import pandas as pd

from foretaksrisiko.models.supervised import FittedSupervised, ScoringPipeline


class SupervisedPyfunc(mlflow.pyfunc.PythonModel):
    def __init__(self, fitted: FittedSupervised) -> None:
        self.pipeline = ScoringPipeline(fitted)

    def predict(self, context, model_input: pd.DataFrame, params=None):
        return self.pipeline.predict(model_input)
