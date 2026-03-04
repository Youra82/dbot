# src/dbot/model/trainer.py
# Training-Loop für das LSTM-Modell
import os
import logging
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.utils.class_weight import compute_class_weight

from dbot.model.lstm_model import LSTMModel, create_model

logger = logging.getLogger(__name__)

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


def train_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    model_config: dict = None,
    epochs: int = 50,
    batch_size: int = 64,
    lr: float = 1e-3,
    patience: int = 10,
) -> tuple:
    """
    Trainiert das LSTM-Modell mit Early Stopping.

    Args:
        X_train: (n, seq_len, features)
        y_train: (n,) Labels 0/1/2
        X_val:   Validierungsdaten
        y_val:   Validierungs-Labels
        model_config: Dict mit Modell-Hyperparametern
        epochs: Maximale Epochen
        batch_size: Batch-Größe
        lr: Lernrate
        patience: Early-Stopping-Geduld (Epochen ohne Verbesserung)

    Returns:
        (model, history): trainiertes Modell + Verlaufsdaten
    """
    n_features = X_train.shape[2]
    model = create_model(n_features, model_config).to(DEVICE)

    # Klassen-gewichtete Loss (ausgeglichen bei ungleicher Verteilung)
    class_weights = compute_class_weight('balanced', classes=np.array([0, 1, 2]), y=y_train)
    weights_tensor = torch.tensor(class_weights, dtype=torch.float32).to(DEVICE)
    criterion = nn.CrossEntropyLoss(weight=weights_tensor)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode='max', factor=0.5, patience=5
    )

    # DataLoader
    X_t = torch.tensor(X_train, dtype=torch.float32)
    y_t = torch.tensor(y_train, dtype=torch.long)
    train_ds = TensorDataset(X_t, y_t)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=False)

    X_v = torch.tensor(X_val, dtype=torch.float32).to(DEVICE)
    y_v = torch.tensor(y_val, dtype=torch.long).to(DEVICE)

    history = {'train_loss': [], 'val_acc': []}
    best_val_acc = 0.0
    best_state = None
    no_improve = 0

    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(DEVICE), y_batch.to(DEVICE)
            optimizer.zero_grad()
            logits = model(X_batch)
            loss = criterion(logits, y_batch)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            total_loss += loss.item() * len(X_batch)

        avg_loss = total_loss / len(X_train)

        # Validierung
        model.eval()
        with torch.no_grad():
            val_logits = model(X_v)
            val_preds = val_logits.argmax(dim=1)
            val_acc = (val_preds == y_v).float().mean().item()

        scheduler.step(val_acc)
        history['train_loss'].append(avg_loss)
        history['val_acc'].append(val_acc)

        logger.info(f"Epoch {epoch+1:3d}/{epochs} | Loss: {avg_loss:.4f} | Val Acc: {val_acc:.4f}")

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= patience:
                logger.info(f"Early Stopping nach Epoch {epoch+1} (keine Verbesserung seit {patience} Epochen).")
                break

    # Bestes Modell wiederherstellen
    if best_state:
        model.load_state_dict(best_state)
    model.to(DEVICE)

    logger.info(f"Training abgeschlossen. Beste Val Accuracy: {best_val_acc:.4f}")
    return model, history


def save_model(model: LSTMModel, path: str, metadata: dict = None):
    """Speichert Modell-Gewichte und Metadaten."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    checkpoint = {
        'state_dict': model.state_dict(),
        'n_features': model.lstm.input_size,
        'hidden_size': model.hidden_size,
        'num_layers': model.num_layers,
        'fc_hidden': model.fc1.out_features,
        'metadata': metadata or {},
    }
    torch.save(checkpoint, path)
    logger.info(f"Modell gespeichert: {path}")


def load_model(path: str) -> LSTMModel:
    """Lädt ein Modell aus einer Checkpoint-Datei."""
    checkpoint = torch.load(path, map_location=DEVICE)
    model = LSTMModel(
        n_features=checkpoint['n_features'],
        hidden_size=checkpoint['hidden_size'],
        num_layers=checkpoint['num_layers'],
        fc_hidden=checkpoint['fc_hidden'],
    ).to(DEVICE)
    model.load_state_dict(checkpoint['state_dict'])
    model.eval()
    logger.info(f"Modell geladen: {path}")
    return model
