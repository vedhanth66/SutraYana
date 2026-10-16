"""Reinforcement Learning Routing Agent with Double DQN and Experience Replay."""
import random
from collections import deque
from pathlib import Path
import numpy as np
import torch
import torch.optim as optim
import torch.nn.functional as F

from .model import DuelingDQN


class ReplayBuffer:
    """Cyclic buffer for experience transitions."""

    def __init__(self, capacity=10000):
        self.buffer = deque(maxlen=capacity)

    def push(self, patch, vec, action, reward, next_patch, next_vec, done, mask):
        self.buffer.append((patch, vec, action, reward, next_patch, next_vec, done, mask))

    def sample(self, batch_size):
        batch = random.sample(self.buffer, batch_size)
        patches, vecs, actions, rewards, next_patches, next_vecs, dones, masks = zip(*batch)
        return (
            torch.from_numpy(np.stack(patches)).float(),
            torch.from_numpy(np.stack(vecs)).float(),
            torch.tensor(actions, dtype=torch.long),
            torch.tensor(rewards, dtype=torch.float32),
            torch.from_numpy(np.stack(next_patches)).float(),
            torch.from_numpy(np.stack(next_vecs)).float(),
            torch.tensor(dones, dtype=torch.float32),
            torch.from_numpy(np.stack(masks)).bool(),
        )

    def __len__(self):
        return len(self.buffer)


class RLRoutingAgent:
    """Agent that selects routing actions via learned Q-policy."""

    def __init__(self, lr=1e-3, gamma=0.98, tau=0.05, device="cpu"):
        self.gamma = gamma
        self.tau = tau
        self.device = torch.device(device or "cpu")

        self.policy_net = DuelingDQN().to(self.device)
        self.target_net = DuelingDQN().to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.memory = ReplayBuffer()

    def select_action(self, patch, vec, mask=None, epsilon=0.0):
        """Select action using epsilon-greedy policy with action masking."""
        valid_actions = [i for i in range(4) if mask is None or mask[i]]
        if not valid_actions:
            valid_actions = list(range(4))

        if random.random() < epsilon:
            return random.choice(valid_actions)

        self.policy_net.eval()
        with torch.no_grad():
            p_t = torch.from_numpy(patch).float().unsqueeze(0).to(self.device)
            v_t = torch.from_numpy(vec).float().unsqueeze(0).to(self.device)
            m_t = torch.from_numpy(mask).bool().unsqueeze(0).to(self.device) if mask is not None else None
            
            q_values = self.policy_net(p_t, v_t, mask=m_t)
            best_action = int(q_values.argmax(dim=-1).item())
            
        return best_action

    def update(self, batch_size=32):
        """Perform one Double-DQN training step."""
        if len(self.memory) < batch_size:
            return 0.0

        patches, vecs, actions, rewards, next_patches, next_vecs, dones, masks = self.memory.sample(batch_size)
        patches = patches.to(self.device)
        vecs = vecs.to(self.device)
        actions = actions.to(self.device).unsqueeze(1)
        rewards = rewards.to(self.device).unsqueeze(1)
        next_patches = next_patches.to(self.device)
        next_vecs = next_vecs.to(self.device)
        dones = dones.to(self.device).unsqueeze(1)
        masks = masks.to(self.device)

        self.policy_net.train()
        q_current = self.policy_net(patches, vecs).gather(1, actions)

        with torch.no_grad():
            next_q_policy = self.policy_net(next_patches, next_vecs, mask=masks)
            next_actions = next_q_policy.argmax(dim=-1, keepdim=True)
            next_q_target = self.target_net(next_patches, next_vecs).gather(1, next_actions)
            q_target = rewards + (1.0 - dones) * self.gamma * next_q_target

        loss = F.smooth_l1_loss(q_current, q_target)

        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.policy_net.parameters(), 1.0)
        self.optimizer.step()

        # Target network update
        for p_target, p_policy in zip(self.target_net.parameters(), self.policy_net.parameters()):
            p_target.data.copy_(self.tau * p_policy.data + (1.0 - self.tau) * p_target.data)

        return float(loss.item())

    def save(self, filepath):
        """Save model checkpoint."""
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "model_state_dict": self.policy_net.state_dict(),
            "target_state_dict": self.target_net.state_dict(),
        }, str(p))

    def load(self, filepath):
        """Load model checkpoint."""
        p = Path(filepath)
        if not p.is_file():
            return False
        checkpoint = torch.load(str(p), map_location=self.device)
        self.policy_net.load_state_dict(checkpoint["model_state_dict"])
        self.target_net.load_state_dict(checkpoint["target_state_dict"])
        self.policy_net.eval()
        return True
