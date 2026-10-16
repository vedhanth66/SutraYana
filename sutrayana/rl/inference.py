"""Inference engine for RL-guided adaptive routing with guaranteed safety fallback."""
import math
from pathlib import Path
from shapely.geometry import LineString, Point
from .agent import RLRoutingAgent
from .env import RoutingEnv, ACTIONS
from ..metrics import compact, length

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "pretrained_router.pt"


class RLAdaptiveRouter:
    """Adaptive neural policy router that proposes high-quality rectilinear paths."""

    def __init__(self, model_path=None, device=None):
        self.device = device
        self.agent = RLRoutingAgent(device=device)
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        self.loaded = False
        if self.model_path.exists():
            self.loaded = self.agent.load(self.model_path)

    def route_leg(self, plan, start, goal, occupied=None, max_steps=150, step_size=0.1):
        """Propose an RL-guided rectilinear path between start and goal.
        
        Returns:
            compacted_polyline: List of (x, y) coordinates if valid, or None.
        """
        manhattan = abs(goal[0] - start[0]) + abs(goal[1] - start[1])
        budget = min(max_steps, max(30, int(manhattan / step_size * 2.2)))
        env = RoutingEnv(plan, step_size=step_size, max_steps=budget)
        patch, vec = env.reset(start=start, goal=goal, occupied=occupied)

        visited = set()
        path = [env.pos]
        visited.add((round(env.pos[0], 3), round(env.pos[1], 3)))

        done = False
        success = False
        
        while not done:
            mask = env.get_action_mask()
            if not mask.any():
                # Dead-end trapped
                break

            action = self.agent.select_action(patch, vec, mask=mask, epsilon=0.0)
            (patch, vec), reward, done, info = env.step(action)
            
            coord_key = (round(env.pos[0], 3), round(env.pos[1], 3))
            if coord_key in visited:
                # Cycle detected: prune loop from path
                idx = len(path) - 1
                while idx >= 0 and (round(path[idx][0], 3), round(path[idx][1], 3)) != coord_key:
                    idx -= 1
                if idx >= 0:
                    path = path[:idx + 1]
            else:
                visited.add(coord_key)
                path.append(env.pos)

            if info.get("success"):
                success = True
                break

        if not success:
            return None

        # Connect arrival point to exact goal via strictly axis-aligned segment(s)
        safe = env.safe_free if env.safe_free is not None else plan.free
        px, py = path[-1]
        gx, gy = float(goal[0]), float(goal[1])
        dx = abs(px - gx)
        dy = abs(py - gy)

        if dx > 1e-8 or dy > 1e-8:
            if dx <= 1e-8:
                path.append((gx, gy))
            elif dy <= 1e-8:
                path.append((gx, gy))
            else:
                seg1a = LineString([(px, py), (gx, py)])
                seg1b = LineString([(gx, py), (gx, gy)])
                valid1 = safe.covers(seg1a) and safe.covers(seg1b)

                seg2a = LineString([(px, py), (px, gy)])
                seg2b = LineString([(px, gy), (gx, gy)])
                valid2 = safe.covers(seg2a) and safe.covers(seg2b)

                if valid1 and valid2:
                    if env.prev_action in (0, 2):
                        path.extend([(gx, py), (gx, gy)])
                    else:
                        path.extend([(px, gy), (gx, gy)])
                elif valid1:
                    path.extend([(gx, py), (gx, gy)])
                elif valid2:
                    path.extend([(px, gy), (gx, gy)])
                else:
                    return None

        # Guarantee exact endpoints
        path[0] = (float(start[0]), float(start[1]))
        path[-1] = (float(goal[0]), float(goal[1]))

        # Axis-aligned check and compaction
        compact_path = compact(path)
        if len(compact_path) < 2:
            return None

        # Strict safety verification
        for a, b in zip(compact_path, compact_path[1:]):
            # Axis-aligned
            if abs(a[0] - b[0]) > 1e-8 and abs(a[1] - b[1]) > 1e-8:
                return None
            seg = LineString([a, b])
            if not safe.covers(seg):
                return None
            # Check terminal clearance
            for r in plan.eligible.values():
                if r.node not in (start, goal) and seg.distance(Point(r.node)) < 0.001:
                    return None

        return compact_path
