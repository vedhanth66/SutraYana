"""Unit and integration tests for SutraYana Reinforcement Learning Adaptive Routing."""
import unittest
from pathlib import Path
import numpy as np
import torch
from shapely.geometry import box, mapping, Point

from sutrayana.model import Plan
from sutrayana.rl import RoutingEnv, DuelingDQN, RLRoutingAgent, RLAdaptiveRouter
from sutrayana.solver import solve_plan
from sutrayana.validation import validate
from test_solver import fixture

ROOT = Path(__file__).resolve().parents[1]


class RLSystemTests(unittest.TestCase):
    def setUp(self):
        self.raw = fixture()
        self.plan = Plan(self.raw)

    def test_routing_env_initialization_and_observation(self):
        env = RoutingEnv(self.plan, step_size=0.1)
        start = self.plan.rooms["left"].node
        goal = self.plan.rooms["right"].node
        patch, vec = env.reset(start=start, goal=goal)

        # Check observation shapes
        self.assertEqual(patch.shape, (3, 7, 7))
        self.assertEqual(vec.shape, (7,))
        self.assertAlmostEqual(env.pos[0], start[0])
        self.assertAlmostEqual(env.pos[1], start[1])

    def test_routing_env_action_mask(self):
        env = RoutingEnv(self.plan, step_size=0.1)
        start = self.plan.rooms["left"].node
        goal = self.plan.rooms["right"].node
        env.reset(start=start, goal=goal)

        mask = env.get_action_mask()
        self.assertEqual(mask.shape, (4,))
        self.assertTrue(mask.dtype == bool)
        # In the center of a 40x40 room, all 4 cardinal steps should be valid
        self.assertTrue(mask.all())

    def test_routing_env_step_and_reward(self):
        env = RoutingEnv(self.plan, step_size=0.1)
        start = (2.0, 2.0)
        goal = (2.0, 2.5)
        env.reset(start=start, goal=goal)

        # Action 1: Up (+y), moves toward goal
        (patch, vec), reward, done, info = env.step(1)
        self.assertAlmostEqual(env.pos[1], 2.1)
        self.assertFalse(done)

    def test_dueling_dqn_forward_and_masking(self):
        model = DuelingDQN()
        patch = torch.randn(2, 3, 7, 7)
        vec = torch.randn(2, 7)
        
        # Test forward pass without mask
        q_vals = model(patch, vec)
        self.assertEqual(q_vals.shape, (2, 4))

        # Test forward pass with mask
        mask = torch.tensor([[True, True, False, False], [False, True, True, False]], dtype=torch.bool)
        masked_q = model(patch, vec, mask=mask)
        self.assertLess(masked_q[0, 2].item(), -1e8)
        self.assertLess(masked_q[0, 3].item(), -1e8)
        self.assertGreater(masked_q[0, 0].item(), -1e8)

    def test_rl_agent_action_selection_and_update(self):
        agent = RLRoutingAgent(device="cpu")
        patch = np.zeros((3, 7, 7), dtype=np.float32)
        vec = np.zeros(7, dtype=np.float32)
        mask = np.array([True, False, False, False], dtype=bool)

        # Action with mask should strictly pick action 0
        action = agent.select_action(patch, vec, mask=mask, epsilon=0.0)
        self.assertEqual(action, 0)

        # Test experience push and learning update
        for i in range(40):
            agent.memory.push(patch, vec, 0, 1.0, patch, vec, False, mask)

        loss = agent.update(batch_size=16)
        self.assertGreaterEqual(loss, 0.0)

    def test_rl_adaptive_router_pretrained_inference(self):
        router = RLAdaptiveRouter()
        self.assertTrue(router.loaded)

        p = Plan(ROOT / "plans/test_01.json")
        start = p.rooms["R01"].node
        goal = p.rooms["R02"].node

        route = router.route_leg(p, start, goal)
        self.assertIsNotNone(route)
        self.assertGreaterEqual(len(route), 2)
        self.assertEqual(route[0], start)
        self.assertEqual(route[-1], goal)

    def test_solve_plan_with_rl_integration(self):
        # Solve plan with RL enabled
        out = solve_plan(self.raw, use_rl=True)
        self.assertTrue(out["solver"]["rl_adaptive_routing"])
        self.assertTrue(validate(self.plan, out)["valid"])
        self.assertEqual(len(out["hubs"]), 1)


if __name__ == "__main__":
    unittest.main()
