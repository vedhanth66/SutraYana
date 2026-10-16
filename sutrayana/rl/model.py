"""PyTorch Dueling Deep Q-Network for Cable Routing."""
import torch
import torch.nn as nn
import torch.nn.functional as F


class DuelingDQN(nn.Module):
    """Dueling Deep Q-Network with CNN spatial encoder and state vector MLP."""

    def __init__(self, in_channels=3, patch_size=7, vec_dim=7, action_dim=4):
        super().__init__()
        self.action_dim = action_dim

        # Spatial patch CNN
        self.conv = nn.Sequential(
            nn.Conv2d(in_channels, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Flatten()
        )
        conv_out_dim = 32 * patch_size * patch_size

        self.conv_fc = nn.Sequential(
            nn.Linear(conv_out_dim, 64),
            nn.ReLU()
        )

        # Vector features MLP
        self.vec_fc = nn.Sequential(
            nn.Linear(vec_dim, 32),
            nn.ReLU()
        )

        # Combined backbone
        self.backbone = nn.Sequential(
            nn.Linear(64 + 32, 64),
            nn.ReLU()
        )

        # Dueling streams
        self.value_stream = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

        self.advantage_stream = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, action_dim)
        )

    def forward(self, patch, vec, mask=None):
        """Compute Q-values for all actions.
        
        Args:
            patch: Tensor of shape (B, C, H, W)
            vec: Tensor of shape (B, D)
            mask: Optional boolean Tensor of shape (B, 4) with True for valid actions.
        """
        c = self.conv_fc(self.conv(patch))
        v = self.vec_fc(vec)
        feat = self.backbone(torch.cat([c, v], dim=-1))

        val = self.value_stream(feat)
        adv = self.advantage_stream(feat)

        # Dueling aggregation: Q(s, a) = V(s) + (A(s, a) - mean(A(s, :)))
        q_values = val + (adv - adv.mean(dim=-1, keepdim=True))

        if mask is not None:
            # Mask out invalid actions
            neg_inf = torch.tensor(-1e9, device=q_values.device, dtype=q_values.dtype)
            q_values = torch.where(mask, q_values, neg_inf)

        return q_values
