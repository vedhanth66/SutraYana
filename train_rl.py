"""CLI tool for training the SutraYana RL Adaptive Routing Agent."""
import argparse
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sutrayana.rl.train import train_rl_agent, collect_available_plans


def main():
    parser = argparse.ArgumentParser(description="Train SutraYana RL Adaptive Routing Policy")
    parser.add_argument("--episodes", type=int, default=200, help="Number of training episodes (default: 200)")
    parser.add_argument("--save", type=str, default=None, help="Path to save weights (.pt)")
    args = parser.parse_args()

    plans = collect_available_plans()
    print(f"Loaded {len(plans)} plans for reinforcement learning training.")
    train_rl_agent(episodes=args.episodes, save_path=args.save, plans=plans, verbose=True)


if __name__ == "__main__":
    main()
