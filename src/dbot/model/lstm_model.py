# src/dbot/model/lstm_model.py
# PyTorch LSTM Modell für 3-Klassen-Klassifikation: Long / Neutral / Short
import torch
import torch.nn as nn

class LSTMModel(nn.Module):
    """
    LSTM-Modell für Krypto-Trendvorhersage.

    Input:  (batch_size, seq_len, n_features)
    Output: (batch_size, 3)  →  [long_prob, neutral_prob, short_prob]

    Klassen:
        0 = LONG  (Preis steigt in den nächsten horizon_candles)
        1 = NEUTRAL (seitwärts)
        2 = SHORT  (Preis fällt)
    """
    def __init__(self, n_features: int, hidden_size: int = 128, num_layers: int = 2,
                 dropout: float = 0.2, fc_hidden: int = 64, n_classes: int = 3):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(p=0.3)
        self.fc1 = nn.Linear(hidden_size, fc_hidden)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(fc_hidden, n_classes)
        # Kein Softmax hier — CrossEntropyLoss erwartet Logits

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, features)
        lstm_out, _ = self.lstm(x)
        # Nehme nur den letzten Zeitschritt
        last_hidden = lstm_out[:, -1, :]          # (batch, hidden_size)
        out = self.dropout(last_hidden)
        out = self.relu(self.fc1(out))             # (batch, fc_hidden)
        out = self.dropout(out)
        logits = self.fc2(out)                     # (batch, 3)
        return logits

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        """Gibt Wahrscheinlichkeiten (Softmax) zurück."""
        logits = self.forward(x)
        return torch.softmax(logits, dim=-1)


def create_model(n_features: int, model_config: dict = None) -> LSTMModel:
    """Erstellt ein LSTM-Modell mit optionaler Konfiguration."""
    cfg = model_config or {}
    return LSTMModel(
        n_features=n_features,
        hidden_size=cfg.get('hidden_size', 128),
        num_layers=cfg.get('num_layers', 2),
        dropout=cfg.get('dropout', 0.2),
        fc_hidden=cfg.get('fc_hidden', 64),
        n_classes=3,
    )
