import pandas as pd
import pytest


@pytest.fixture
def raw_sample():
    """A few rows in the original Kaggle PaySim format (copied from the public file)."""
    return pd.DataFrame(
        {
            "step": [1, 1, 1, 1, 25],
            "type": ["PAYMENT", "TRANSFER", "CASH_OUT", "CASH_IN", "DEBIT"],
            "amount": [9839.64, 181.0, 181.0, 5000.0, 120.5],
            "nameOrig": ["C1231006815", "C1305486145", "C840083671", "C111", "C222"],
            "oldbalanceOrg": [170136.0, 181.0, 181.0, 100.0, 500.0],
            "newbalanceOrig": [160296.36, 0.0, 0.0, 5100.0, 379.5],
            "nameDest": ["M1979787155", "C553264065", "C38997010", "C333", "C444"],
            "oldbalanceDest": [0.0, 0.0, 21182.0, 10.0, 0.0],
            "newbalanceDest": [0.0, 0.0, 0.0, 0.0, 120.5],
            "isFraud": [0, 1, 1, 0, 0],
            "isFlaggedFraud": [0, 0, 0, 0, 0],
        }
    )
