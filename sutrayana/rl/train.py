"""Training loop for RL Adaptive Routing Agent."""
import math
import random
import time
from pathlib import Path
import numpy as np

from .env import RoutingEnv
from .agent import RLRoutingAgent
from ..model import Plan

ROOT = Path(__file__).resolve().parents[2]


def collect_available_plans():
    """Gather available floor plan JSON files for diverse training."""
    plans = []
    for folder in ("plans", "examples", "."):
        pdir = ROOT / folder
        if not pdir.is_dir():
            continue
        for p in sorted(pdir.glob("*.json")):
            if "result" in p.name or "solution" in p.name or "output" in p.name:
                continue
            try:
                plan = Plan(str(p))
                if len(plan.eligible) >= 2:
                    plans.append(plan)
            except Exception:
                pass
    return plans


def train_rl_agent(episodes=100, save_path=None, plans=None, verbose=True):
    """Train the Dueling-DQN agent on floor plan routing tasks."""
    if plans is None or len(plans) == 0:
        plans = collect_available_plans()
    if not plans:
        raise ValueError("No valid floor plans found to train on.")

    save_path = Path(save_path) if save_path else (Path(__file__).resolve().parent / "models" / "pretrained_router.pt")
    agent = RLRoutingAgent()
    
    eps_start = 1.0
    eps_end = 0.05
    eps_decay = episodes * 0.65

    rewards_history = []
    success_count = 0
    t0 = time.perf_counter()

    if verbose:
        print(f"=== Starting RL Agent Training ({episodes} episodes across {len(plans)} plans) ===", flush=True)

    envs = [RoutingEnv(p, step_size=0.1, max_steps=120) for p in plans]
    step_total = 0

    for ep in range(1, episodes + 1):
        env = random.choice(envs)
        plan = env.plan
        
        occupied = []
        if random.random() < 0.35 and len(plan.eligible) >= 3:
            pts = [r.node for r in plan.eligible.values()]
            occupied = [(pts[i], pts[i+1]) for i in range(len(pts)-1)]

        patch, vec = env.reset(occupied=occupied)
        epsilon = eps_end + (eps_start - eps_end) * math.exp(-1.0 * ep / max(eps_decay, 1))

        ep_reward = 0.0
        done = False

        while not done:
            step_total += 1
            mask = env.get_action_mask()
            action = agent.select_action(patch, vec, mask=mask, epsilon=epsilon)
            (next_patch, next_vec), reward, done, info = env.step(action)

            next_mask = env.get_action_mask() if not done else np.zeros(4, dtype=bool)
            agent.memory.push(patch, vec, action, reward, next_patch, next_vec, done, next_mask)

            patch, vec = next_patch, next_vec
            ep_reward += reward

            # Update Q-network every 4 steps
            if step_total % 4 == 0 and len(agent.memory) >= 32:
                agent.update(batch_size=32)

        rewards_history.append(ep_reward)
        if info.get("success"):
            success_count += 1

        if verbose and (ep % 10 == 0 or ep == episodes):
            avg_rew = float(np.mean(rewards_history[-10:]))
            succ_pct = (success_count / ep) * 100.0
            print(f"Episode {ep:3d}/{episodes} | Avg Reward (last 10): {avg_rew:6.2f} | Success: {succ_pct:5.1f}% | Eps: {epsilon:.3f}", flush=True)

    agent.save(save_path)
    elapsed = time.perf_counter() - t0
    if verbose:
        print(f"=== Training complete in {elapsed:.2f}s! Saved weights to: {save_path} ===", flush=True)

    return agent
