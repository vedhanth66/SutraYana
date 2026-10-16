"""Markov Decision Process (MDP) Routing Environment for SutraYana (High-Performance Vectorized)."""
import math
import numpy as np
import shapely
from shapely.geometry import Point, LineString

ACTIONS = np.array([
    [1.0, 0.0],   # 0: Right
    [0.0, 1.0],   # 1: Up
    [-1.0, 0.0],  # 2: Left
    [0.0, -1.0],  # 3: Down
], dtype=np.float64)

ACTION_NAMES = ["RIGHT", "UP", "LEFT", "DOWN"]


class RoutingEnv:
    """Discrete grid-action routing environment over a continuous geometric Plan.
    
    The agent moves in cardinal directions to connect start -> goal while minimizing
    the competition cost J = L + 5X + O + 0.5B and strictly respecting barriers.
    """

    def __init__(self, plan, step_size=0.1, patch_radius=3, max_steps=200):
        self.plan = plan
        self.step_size = float(step_size)
        self.patch_radius = patch_radius
        self.patch_size = 2 * patch_radius + 1  # 7x7
        self.max_steps = max_steps
        
        # Spatial extent for normalization
        bounds = plan.inner.bounds
        self.diag = max(math.hypot(bounds[2] - bounds[0], bounds[3] - bounds[1]), 1.0)
        
        if hasattr(plan, "_safe_free"):
            self.safe_free = plan._safe_free
        elif hasattr(plan, "free") and plan.free is not None:
            safe = plan.free.buffer(-0.000001, join_style=2)
            shapely.prepare(safe)
            plan._safe_free = safe
            self.safe_free = safe
        else:
            self.safe_free = None

        # Precompute relative patch coordinate grid
        dys = [(self.patch_radius - i) * self.step_size for i in range(self.patch_size)]
        dxs = [(j - self.patch_radius) * self.step_size for j in range(self.patch_size)]
        grid_dy, grid_dx = np.meshgrid(dys, dxs, indexing="ij")
        self.rel_dx = grid_dx.ravel()
        self.rel_dy = grid_dy.ravel()

        self.terminals = [r.node for r in plan.eligible.values()]
        
        self.start = None
        self.goal = None
        self.pos = None
        self.prev_action = None
        self.step_count = 0
        self.trajectory = []
        self.occupied_segments = []
        self.other_nodes = []
        self.other_nodes_arr = np.empty((0, 2), dtype=np.float64)

    def reset(self, start=None, goal=None, occupied=None):
        """Reset the environment for a new routing episode."""
        if start is None or goal is None:
            eligible = list(self.plan.eligible.values())
            if len(eligible) >= 2:
                pair = np.random.choice(len(eligible), size=2, replace=False)
                start = eligible[pair[0]].node
                goal = eligible[pair[1]].node
            elif len(eligible) == 1:
                start = eligible[0].node
                cands = self.plan.hub_candidates(eligible[0].id)
                goal = cands[0] if cands else (start[0] + 0.5, start[1] + 0.5)
            else:
                start = (1.0, 1.0)
                goal = (3.0, 3.0)

        self.start = (float(start[0]), float(start[1]))
        self.goal = (float(goal[0]), float(goal[1]))
        self.pos = self.start
        self.prev_action = None
        self.step_count = 0
        self.trajectory = [self.pos]
        self.occupied_segments = occupied or []
        
        self.other_nodes = [r.node for r in self.plan.eligible.values() if r.node not in (self.start, self.goal)]
        self.other_nodes_arr = np.array(self.other_nodes, dtype=np.float64) if self.other_nodes else np.empty((0, 2), dtype=np.float64)

        return self.get_observation()

    def get_action_mask(self):
        """Compute vectorized boolean validity mask for actions [right, up, left, down]."""
        cx, cy = self.pos
        next_xy = np.column_stack([cx + ACTIONS[:, 0] * self.step_size, cy + ACTIONS[:, 1] * self.step_size])
        
        # Build 4 candidate line segments
        cur_arr = np.tile([cx, cy], (4, 1))
        coords = np.stack([cur_arr, next_xy], axis=1)  # shape (4, 2, 2)
        segs = shapely.linestrings(coords)

        # 1. Must be covered by safe free space
        if self.safe_free is not None:
            mask = shapely.covers(self.safe_free, segs)
        else:
            mask = np.ones(4, dtype=bool)

        # 2. Must not pass unintended fixed nodes within 1mm
        if len(self.other_nodes_arr) > 0 and mask.any():
            valid_indices = np.flatnonzero(mask)
            for idx in valid_indices:
                seg = segs[idx]
                for on in self.other_nodes:
                    if seg.distance(Point(on)) < 0.001:
                        mask[idx] = False
                        break

        return mask

    def get_observation(self):
        """Build observation: (patch: [C, H, W], state_vec: [D])."""
        H = W = self.patch_size
        patch = np.zeros((3, H, W), dtype=np.float32)
        cx, cy = self.pos

        # Ch 0: Walkable free space (vectorized GEOS check)
        if self.safe_free is not None:
            xs = cx + self.rel_dx
            ys = cy + self.rel_dy
            walkable = shapely.contains_xy(self.safe_free, xs, ys)
            patch[0] = walkable.reshape(H, W)

        # Ch 1: Occupied lines nearby (fast bounding-box filter)
        if self.occupied_segments:
            p_min_x, p_max_x = cx - self.patch_radius * self.step_size - 0.05, cx + self.patch_radius * self.step_size + 0.05
            p_min_y, p_max_y = cy - self.patch_radius * self.step_size - 0.05, cy + self.patch_radius * self.step_size + 0.05
            for a, b in self.occupied_segments:
                if max(a[0], b[0]) < p_min_x or min(a[0], b[0]) > p_max_x or max(a[1], b[1]) < p_min_y or min(a[1], b[1]) > p_max_y:
                    continue
                seg = LineString([a, b])
                for i in range(H):
                    for j in range(W):
                        pt = Point(cx + self.rel_dx[i * W + j], cy + self.rel_dy[i * W + j])
                        if seg.distance(pt) < 0.02:
                            patch[1, i, j] = 1.0

        # Ch 2: Other fixed nodes
        if len(self.other_nodes_arr) > 0:
            for on in self.other_nodes:
                dists = np.hypot(cx + self.rel_dx - on[0], cy + self.rel_dy - on[1])
                close = dists < 0.02
                if close.any():
                    patch[2] = np.maximum(patch[2], close.reshape(H, W).astype(np.float32))

        # Vector features: Direction one-hot (4), relative goal vector (2), normalized dist (1)
        dir_vec = np.zeros(4, dtype=np.float32)
        if self.prev_action is not None:
            dir_vec[self.prev_action] = 1.0
            
        dx_goal = (self.goal[0] - cx) / self.diag
        dy_goal = (self.goal[1] - cy) / self.diag
        dist_goal = math.hypot(self.goal[0] - cx, self.goal[1] - cy) / self.diag
        
        state_vec = np.concatenate([
            dir_vec,
            np.array([dx_goal, dy_goal, dist_goal], dtype=np.float32)
        ])
        
        return patch, state_vec

    def step(self, action):
        """Take a step in the environment."""
        self.step_count += 1
        dx, dy = ACTIONS[action]
        prev_pos = self.pos
        new_pos = (prev_pos[0] + dx * self.step_size, prev_pos[1] + dy * self.step_size)
        seg = LineString([prev_pos, new_pos])
        
        prev_dist = math.hypot(self.goal[0] - prev_pos[0], self.goal[1] - prev_pos[1])
        curr_dist = math.hypot(self.goal[0] - new_pos[0], self.goal[1] - new_pos[1])
        
        # Hard collision check
        is_free = (self.safe_free is None) or self.safe_free.covers(seg)
        hit_node = any(seg.distance(Point(on)) < 0.001 for on in self.other_nodes)
        
        if not is_free or hit_node:
            reward = -10.0
            done = True
            info = {"success": False, "reason": "collision"}
            return self.get_observation(), reward, done, info

        # Advance agent
        self.pos = new_pos
        self.trajectory.append(new_pos)
        
        # Reward calculation: J = L + 5X + O + 0.5B
        reward = -0.1 * self.step_size  # Length penalty (L)
        
        # Bend penalty (B)
        if self.prev_action is not None and action != self.prev_action:
            reward -= 0.05
            
        # Overlap penalty (O) and crossing penalty (X)
        if self.occupied_segments:
            s_min_x, s_max_x = min(prev_pos[0], new_pos[0]) - 0.005, max(prev_pos[0], new_pos[0]) + 0.005
            s_min_y, s_max_y = min(prev_pos[1], new_pos[1]) - 0.005, max(prev_pos[1], new_pos[1]) + 0.005
            for a, b in self.occupied_segments:
                if max(a[0], b[0]) < s_min_x or min(a[0], b[0]) > s_max_x or max(a[1], b[1]) < s_min_y or min(a[1], b[1]) > s_max_y:
                    continue
                occ_seg = LineString([a, b])
                if seg.crosses(occ_seg):
                    reward -= 0.5
                elif seg.distance(occ_seg) < 0.001:
                    reward -= 0.1 * self.step_size

        # Distance potential shaping
        reward += 1.2 * (prev_dist - curr_dist)
        
        self.prev_action = action
        
        # Check goal reached
        if curr_dist <= self.step_size * 0.75 or math.hypot(self.goal[0] - new_pos[0], self.goal[1] - new_pos[1]) < 0.001:
            reward += 10.0
            self.trajectory[-1] = self.goal
            done = True
            info = {"success": True, "reason": "goal_reached"}
        elif self.step_count >= self.max_steps:
            reward -= 2.0
            done = True
            info = {"success": False, "reason": "timeout"}
        else:
            done = False
            info = {"success": False, "reason": "in_progress"}

        return self.get_observation(), reward, done, info
