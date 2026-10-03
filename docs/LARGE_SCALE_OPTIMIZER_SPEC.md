# GEMSEO Large-Scale Optimizer — Specification

Status: draft for review. Working name of the package: `gemseo-lso` (Large-Scale Optimizer), in `plugins/gemseo_lso/` (open point 1).

## 1. Purpose

A gradient-based optimizer, written entirely in Python (NumPy and SciPy), for problems of **10⁵ to 10⁶ design variables and as many inequality constraints**, where:

- one evaluation of the model gives the objective and **all** the constraint values (seconds to minutes);
- the **gradient of each constraint costs about one evaluation**: the Jacobian can only be computed row by row, and a full Jacobian (10⁵ to 10⁶ rows) is out of reach at every iteration;
- at the optimum, **a few percent** of the constraints are active;
- the machines have up to 1 TB of memory and many cores.

No existing optimizer of GEMSEO fits: SLSQP is dense and cubic in the size; NLopt's MMA takes a dense m × n Jacobian of all constraints; IPOPT needs every constraint gradient at every iteration (its barrier involves them all) and a compiled solver; the Augmented Lagrangian of GEMSEO needs a Jacobian at each of its many inner iterations.

The design goal is therefore to **minimize the number of Jacobian rows computed**, then to keep the cost of the optimizer itself small next to the evaluations.

### 1.1 Principles

1. **Gradients are the currency.** Every design choice is judged by the number of constraint gradients it asks for.
2. **Correct whatever the screening.** Ignoring a constraint is a bet; the bet is checked at every new point with the constraint values, which are always all known, and a lost bet is corrected before a step is accepted.
3. **Written from the literature**, in Python, MIT-licensed. No code is copied from other implementations (some are GPL).
4. **Steppable and inspectable.** The optimizer runs iteration by iteration; its whole state can be saved and restored exactly; its settings can change between two iterations without a restart. This is what makes it pilotable by Claude (§ 8).
5. **Pure Python first.** NumPy and multithreaded BLAS carry the heavy operations; Numba is added only where a measurement shows a Python loop costs more than 1 % of an iteration. It did at 10⁶ variables (§ 3.7): the loops over the variables of the dual are Numba kernels, with a NumPy version giving the same results when Numba is missing.

### 1.2 Out of scope (first version)

- Many equality constraints (a few are supported, § 3.4).
- Integer variables, multiple objectives, global optimization.
- Second derivatives.
- Matrix-free weighted adjoints (Jᵀw in one solve): a later mode (§ 10, open point 4).

## 2. Glossary

| Term | Meaning |
|---|---|
| **Row** | The gradient of one constraint component with respect to all design variables (a row of the Jacobian). |
| **Working set** S | The constraints whose rows are used at an iteration; the others are screened out. |
| **Screening** | Choosing S from the constraint values. |
| **Stale row** | A row computed at an earlier iterate and reused. |
| **Outer iteration** | One new iterate: rows for S, one subproblem, one accepted step. |
| **Inner iteration** | GCMMA only: a tighter subproblem at the same iterate, when the previous one was not conservative; needs values only. |

## 3. Algorithm

### 3.1 Problem

```
minimize    f(x)
subject to  g_i(x) ≤ 0,        i = 1 … m       (m up to 10⁶)
            h_k(x) = 0,        k = 1 … p       (p small, § 3.4)
            x_min ≤ x ≤ x_max                  (n up to 10⁶)
```

The design space is normalized to [0, 1] (GEMSEO's `normalize_design_space`, on by default). The optimizer follows the scale of the objective and of each constraint by itself: the subproblem (§ 3.6) and the screening (§ 3.3) work in their units; only the feasibility tolerances (`ineq_tolerance`, `eq_tolerance`) are in the units of the constraints.

### 3.2 Outer loop

At iteration k, with the iterate x_k, all values f(x_k), g(x_k) and the state of the method:

1. **Screen**: choose the working set S_k (§ 3.3).
2. **Rows**: obtain the rows of S_k — computed at x_k, or reused if stale rows are allowed (§ 3.5) — in **one batch request**, so that the model can compute them in parallel. Plus the gradient of f.
3. **Subproblem**: build the MMA approximation of f and of the constraints of S_k at x_k (§ 3.6) and solve it (§ 3.7): candidate x̂.
4. **Evaluate** x̂: f and **all** constraints.
5. **Check the screening**: if a screened-out constraint i ∉ S_k is violated at x̂ (beyond `ineq_tolerance`), it joins S_k — even beyond `max_working_set` —, its row is computed at x_k and the subproblem is solved again from step 3 (x̂ is not accepted). At most `max_screening_repairs` times; then x̂ is accepted and the constraint, now close to activity, is in the next working set. A constraint that only comes closer to activity needs no repair: the next screening takes it.
6. **Conservativeness** (GCMMA only, § 3.6): if the approximations of f or of the constraints of S_k are not conservative at x̂, their curvature terms grow and the subproblem is solved again (inner iteration: values only, no row).
7. **Accept**: x_{k+1} = x̂; update the asymptotes, the multipliers, the history.
8. **Stop** (§ 3.8), or continue.

### 3.3 Screening

The working set is:

```
S_k = { i : g_i(x_k) ≥ −δ_k }                     (close to activity or violated)
    ∪ { i : λ_i^(k−1) > 0 }                        (active in the last subproblem)
    ∪ { i : i ∈ S_(k−1) and g_i(x_k) ≥ −δ_keep }   (hysteresis, avoids churn)
```

truncated to `max_working_set` by keeping the largest `g_i`, never below the constraints active in the last subproblem: capping one would drop its multiplier — the subproblem ignoring it, a repair adding it back at every iteration, and the KKT residual missing its term (at 10⁶ variables, 20,057 active constraints for a cap of 20,000 left the residual at 0.5 with the multipliers exact to 1e-5). The active set alone may thus exceed the cap. The margin δ_k is twice the largest change of a constraint over the last step, between `screening_margin_min` (0.05) and `screening_margin` (0.3): wide while the iterates move, narrow as they converge. A multiplier counts as active above 10⁻⁶ of the largest one (the interior point leaves tiny positive multipliers on inactive constraints). Only values are needed to screen.

**In the units of the subproblem.** The values, margins and multipliers of the screening (and `fresh_margin`, § 3.5) are those of the constraints divided by their scales (§ 3.6): each constraint keeps the scale of its last row (`constraint_scales` in the state), a constraint whose row was never computed takes the median of the known scales, and before the first screening the row of the largest constraint gives one. On the synthetic problem, constraints multiplied by 10³ or 10⁻³ now ask for the same 3,188 rows in 19 iterations as the original; before, 10⁻³ asked for every row at every iteration (40,000 rows) and 10³ needed repairs (5 on the synthetic problem, 65 on a stress-constrained bracket).

Expected size: with 1 to 5 % of active constraints at the optimum, S holds 2 to 4 times the active set, i.e. about 5 to 10 % of the constraints — 10 to 20 times fewer rows than the full Jacobian.

**Outside the feasible domain.** From a design that violates most of the constraints, the working set above would hold nearly all of them: each iteration would cost the most (a dual of as many multipliers as rows) to leave a domain where most of the constraints are not yet the ones that matter. When more than `violated_share` (0.25) of the inequality constraints are violated at the iterate, the run is *outside* (until the share falls under half of it): the working set keeps the `violated_working_set` (0.1, at least 100 rows) share of the constraints with the largest values, the active ones of the last subproblem always kept, and the check of step 5 of § 3.2 changes its bet. Inside, a screened-out constraint is a bet that it stays satisfied, and every violated one at x̂ is added; outside, most of them are violated and stay so while the worst are corrected, so the bet is that none gets worse: only the screened-out constraints violated at x̂ *and* more than at x_k (by more than `ineq_tolerance`) are added. The reports say it (`outside`). The thresholds are live settings; `violated_share` = 1 never goes outside, and inside the domain the iterates are those of the screening above, bit for bit.

### 3.4 Equality constraints

A few equality constraints (`p ≤ max_equality`, default 100) are replaced by the pair `h_k − ε ≤ 0`, `−h_k − ε ≤ 0`, always in the working set. The band ε starts at `max(1, max |h(x₀)|)` and is multiplied by `equality_band_decrease` (0.5) at each iteration down to `eq_tolerance`: with ε = `eq_tolerance` from the start, MMA has no room to move along a curved constraint and crawls (measured on HS 6 and HS 7). Many equality constraints are out of scope (§ 1.2).

### 3.5 Row cache and stale rows

Rows are kept in a cache, by constraint index, with the iterate they were computed at. Policy, set by `row_refresh`:

- `always` (default): every row of S_k is computed at x_k. The reference behaviour.
- `near_active`: rows of constraints with `g_i ≥ −δ_fresh` are computed at x_k; the other rows of S_k may be reused if their age is at most `max_row_age` iterations and the step since then is below `max_row_step` (normalized). A constraint that later turns out to matter is caught by the screening check (§ 3.2, step 5) and its row refreshed.

Stale rows break the theory of MMA (open point 2); `near_active` is therefore optional, measured on the benchmarks (§ 9), and a setting Claude may change (§ 8).

Memory: the cache holds at most `max_working_set × n` values, in float64 by default (`row_dtype`): 10⁴ rows of 10⁵ variables take 8 GB, of 10⁶ variables 80 GB (half in float32). Rows can be sparse (`scipy.sparse`), then stored and used as such. The cache keeps the rows of the working set only, and is not part of the saved state (it may hold gigabytes): a resumed run computes its rows again at its first iteration.

### 3.6 MMA and GCMMA approximations

From Svanberg, *The method of moving asymptotes* (1987), and *A class of globally convergent optimization methods based on conservative convex separable approximations* (2002). For each function φ ∈ {f} ∪ {g_i, i ∈ S_k}, at x_k, with lower and upper asymptotes l, u:

```
φ̃(x) = Σ_j [ p_j / (u_j − x_j) + q_j / (x_j − l_j) ] + r
p_j = (u_j − x_kj)² (1.001 (∂φ/∂x_j)⁺ + 0.001 (∂φ/∂x_j)⁻ + ρ_φ / (x_max,j − x_min,j))
q_j = (x_kj − l_j)² (0.001 (∂φ/∂x_j)⁺ + 1.001 (∂φ/∂x_j)⁻ + ρ_φ / (x_max,j − x_min,j))
```

with r such that φ̃(x_k) = φ(x_k). ρ_φ is a small constant in MMA (10⁻⁵) and grows in the inner iterations of GCMMA until φ̃(x̂) ≥ φ(x̂).

**Evaluated around the iterate.** With `d = x − x_k`, `A_j = (u_j − x_kj) d_j / (u_j − x_j)` and `B_j = (x_kj − l_j) d_j / (x_j − l_j)`, the approximation is `φ̃(x) = φ(x_k) + Σ_j c⁺_j A_j − c⁻_j B_j`, where `c⁺` and `c⁻` are the brackets of `p` and `q`: every term is proportional to the step. Computed through `r` instead, it subtracts sums of the size of the gradients; with rows in float32, that cancellation left the KKT residual at 1e-5 and an error of 1e-5 on the optimum. Around the iterate, float32 rows meet a KKT tolerance of 1e-6 like float64 rows (plan 66). The products with the rows are made in their precision (a float64 vector times float32 rows would copy the rows into float64 at each product), their results in float64.

**MMA switches to GCMMA by itself.** When MMA's best KKT residual has not decreased by 10 % over `kkt_stall_iterations` iterations while its iterates still move (more than 1e-3 of the ranges), it cycles: it goes on as GCMMA, and says so in the reports (`method`) and the state (`gcmma_since`). HS 21 and the synthetic problem, where MMA cycled, now converge.

**MMA or GCMMA.** The curvature MMA gives a function in a variable is proportional to the gradient in that variable. Near the optimum, a variable of an objective with its own curvature (a quadratic) and no active constraint has a gradient going to zero: its approximation becomes too flat, the steps overshoot, the asymptotes shrink to their floor (1 % of the range) and MMA settles into a two-point cycle (measured on the synthetic problem of § 9 and on HS 21). GCMMA's conservative approximations remove it. MMA suits the structural problems it was made for (compliance, stresses), whose curvature follows their gradient; GCMMA is the choice for the others, at the price of the evaluations of its inner iterations.

Asymptotes, per variable: at the first two iterations `x_k ∓ asymptote_init × (x_max − x_min)` (default 0.5); then widened by `asymptote_increase` (1.2) when the variable moves in the same direction twice, narrowed by `asymptote_decrease` (0.7) when it oscillates, kept between 0.01 and 10 times the range. Move limits: the subproblem keeps x within `move_limit` (0.5 of the range) of x_k and away from the asymptotes (10 % of the distance).

p and q are never stored for all constraints: they are computed from the rows, the asymptotes and x_k when the subproblem needs them (memory O(|S| n) for the rows only).

To guarantee a feasible subproblem, each constraint of S has an elastic variable y_i ≥ 0 with cost `c_i y_i + ½ y_i²` (`elastic_cost`, default 1000), as in Svanberg's standard form.

**The subproblem follows the scale of the problem.** Its objective is divided by the largest change of the objective when one variable crosses its range, at the start (`objective_scale` in the state), and each of its constraints by its own, from its row (the smallest positive scale for a row of zeros): every function of the subproblem is on a scale of 1 per variable, where Svanberg's constants (the curvature 10⁻⁵ of MMA, the elastic cost) are meant, and its tolerances mean the same whatever the units. The multipliers and elastic variables are brought back to the units of the problem, for the screening and the KKT residual. Unscaled, a cantilever whose objective was multiplied by 10⁴ made MMA oscillate for 190 iterations (an elastic cost of 1000 against multipliers of 10⁴), and one multiplied by 10⁻⁴ took 3.8 s in the interior point (absolute tolerances); scaled, objective and constraints multiplied by 10^±4 give the same iterates as the original, in as many iterations (test). The largest change per variable, not over all the variables: a volume over n elements would have per-variable gradients of 1/n, below the curvature 10⁻⁵ of MMA — which then kept the variables away from their bounds. The dual value leaves out the constant φ(x_k), of the order of n times the largest term of the gradient: it drowned the ascent of the last Newton steps in its rounding (violations of 2·10⁻⁵ at the end of a restoration). At the end of the interior point, a variable whose bound multiplier exceeds its distance to the bound is put on it: the last barrier (10⁻⁹) leaves it at 10⁻⁹/ξ, 2.5·10⁻⁶ for a gradient of 4·10⁻⁴, not at the bound for the KKT residual.

### 3.7 Subproblem solver

The subproblem is convex and separable: for given multipliers λ ∈ ℝ₊^|S|, the minimizing x(λ) is known in closed form, variable by variable, clipped to the move limits. It is solved **in its dual**: maximize the concave, continuously differentiable dual function over λ ≥ 0 and the elastic variables, with a bound-constrained quasi-Newton method (SciPy's L-BFGS-B on the dual variables).

- **Projected Newton on the dual** (`dual_solver="newton"`, the default when the rows are sparse and |S| > `dense_dual_threshold`). The Hessian of the dual is −(S D⁻¹ Sᵀ + diag(1/d) on the elastic excess), where S is the Jacobian of the approximated constraints at x(λ) — as sparse as the rows — and D the diagonal curvature of the Lagrangian, zero where x is at a move limit; the rank-two terms of the GCMMA ρ are added by Woodbury. Each step factorizes the free block with SuperLU, blocks the multipliers at zero with a satisfied constraint, and takes an Armijo step along the projected direction, falling back to the projected gradient; a Levenberg–Marquardt damping (×10 when the step had to be halved more than once, ÷10 when the full step was taken) handles the kinks where variables reach their move limits. At most 30 steps: the adaptive tolerance below is usually met in fewer, and the step is then checked on the true constraints anyway. L-BFGS-B stalls on the first subproblems at 10⁶ variables (a start violating many constraints makes the dual ill-conditioned); Newton solves them in 20 to 40 steps. At 10⁵ variables and constraints, the whole run went from 24 s to 5.5 s.
- **Two defects of the Newton solver, found by forcing it on a start violating every constraint** (an exploration of the Claude copilot: a noisy design, a working set of every constraint). At `λ = 0` every variable sits at a limit of its move, the curvature of the Lagrangian is zero and the Newton system is singular; its regularization, proportional to the largest diagonal term, vanished too (a direction of 8·10³⁰⁰), the dual became `NaN`, the search of the step failed 40 times and the loop left on its `else: break` — read as "at the precision of the dual" — returning the zero multipliers, with a projected gradient of 8 against a tolerance of 10⁻⁵: a subproblem ignoring the constraints, the design emptied in three iterations (volume 0, constraint −1). Now the shift has a floor of the size a step of the multipliers may have (`STEP_SCALE` times the elastic cost), and a failed search with a projected gradient above `STALLED_FACTOR` times the tolerance hands over to L-BFGS-B from where Newton is. Each correction alone is enough on the test case. Measured on that start (1,296 variables), Newton gave the design of L-BFGS-B but was slower, 25.7 s against 7 s for six iterations: 73 % of its time was SciPy's product `S D⁻¹ Sᵀ` of sparse matrices, on one core, of rows that are far from sparse, and 16 % the construction of the curvature. Now `kernels.gram` computes that matrix, dense, from the nonzeros of the rows, in a Numba loop on every core (one row of the result per iteration; 2 to 47 ms where SciPy took 0.2 to 0.6 s and dense BLAS up to 0.7 s, which multiplies the zeros too), the system is factorized by Cholesky (LU if it is not positive definite), and `curvature` forms its pattern in one pass over the nonzeros that |G| and G share. The kernel computes the lower triangle only (the matrix is symmetric, Cholesky reads one triangle), the rows of the result taken from both ends in turn so that the cores share the work, and the data of the curvature pattern are combined in one Numba pass (`kernels.combine`, 20 ms on 500,000 entries in NumPy). Newton falls to 4.4 s, against 6.7 s for L-BFGS-B, for ten times fewer evaluations of the dual — which it does not converge on this start: its 30 steps are all used and the dual value is still rising slowly (20 % short at step 16 of one solve), so reusing the Hessian between steps would not help, and a cheaper step is the lever; the matrix is dense, of the square of the rows of the working set (72 MB for 3,000, 800 MB for 10,000).
- **Fused kernels.** For given λ, x(λ), the approximated constraints and objective, and the vectors of the Hessian are elementwise over the variables. Written in NumPy they took 82 % of an iteration at 10⁶ variables (a temporary per operation, one core, the steps computed twice per evaluation); they are one pass each, written once in NumPy and once as a parallel Numba kernel (`prange`, compiled on first use and cached on disk), which the optimizer uses when Numba is installed. The products λᵀ|G|, λᵀG and the steps A − B, A + B stay in the precision of the rows (float32), the kernels computing in float64: no conversion of a vector of the size of the design space. The kernels read more than they compute (about 90 MB per evaluation at 10⁶ variables, near the memory bandwidth): they are vectorized (`error_model="numpy"`, `fastmath` limited to reordering the sums) and recompute (u − x_k)² and (x_k − l)² instead of reading them, 3.65 ms to 2.88 ms an evaluation; SIMD alone gained 3 %. The first subproblem at 10⁶ variables and constraints went from 127 s to 12 s (12 cores); the whole run at 10⁵ from 5.5 s to 3 s.

- **Failures are not silent** (plan 74). L-BFGS-B may end on a failed line search ("ABNORMAL") on an ill-conditioned dual, its projected gradient far above the tolerance: it is started again (`RESTARTS` = 2, from where it stopped, then from the origin) only when it did not succeed and the projected gradient is above the tolerance. The interior point reports `converged = False` when a barrier stage exhausts its 200 Newton iterations, and `checked` then solves the subproblem again with the dual solver, warm-started from its multipliers. Its reduced system is equilibrated (`solve_scaled`), the barrier terms spanning tens of orders of magnitude.
- One dual evaluation costs two products with the rows (O(|S| n), multithreaded BLAS): about 10⁹ operations for 10⁴ rows of 10⁵ variables, a fraction of a second.
- The dual is warm-started from the multipliers of the previous iteration.
- Its tolerance adjusts itself: a tenth of the last step (the largest move of a variable, relative to its range), at most 1e-2 — coarse while the iterates move far, fine as they settle; at least `dual_tolerance`, and a tenth of the feasibility tolerances divided by the largest scale of the constraints (the units of the subproblem), which the approximated constraints must meet at the end. Tied to the KKT residual instead, it made a circle: a coarse dual gives inaccurate multipliers, which keep the residual, hence the tolerance, high. At 10⁵ variables and constraints, the run went from 35 s to 24 s, and closer to the solution.
- When |S| is between 10 and `dense_dual_threshold` (default 100), a primal-dual interior-point method on the perturbed KKT conditions of the subproblem, reduced to a dense system of size |S|, is used instead: more accurate multipliers. Its cost grows with |S|² n, hence the small threshold, and `auto` leaves it beyond n |S|² = 10⁷. Below 10 constraints its ~100 Newton iterations cost far more than L-BFGS-B on a dual of at most 10 variables: on Svanberg's beam of 100 segments (one constraint), 6.5 s against 0.2 s, with the same iterates and accuracy, and no end in 250 s at 1,000 segments (0.7 s with L-BFGS-B); on Hock and Schittkowski's problems 0.44 s against 0.03 s. The reduced system is equilibrated by its diagonal before its factorization: the diagonal of the barrier terms spans twenty orders of magnitude at the end, a conditioning of 10⁻²⁰ that made LAPACK warn of an inaccurate result on the truss problems.
- Measured (plan 65, 12 cores, n = 10⁵, dense rows): a subproblem of 2,000 constraints in 3.5 s and of 5,000 in 8.2 s, about 20 dual evaluations of 0.16 s to 0.4 s. A nearly infeasible subproblem — hundreds of violated constraints, their multipliers at the elastic cost and many variables at their move limits — makes the dual piecewise and L-BFGS-B slow (about 1,400 evaluations, 4 minutes at 2,000 constraints); a diagonal scaling of the dual does not help. To be measured on the benchmarks (plan 69) and improved if it matters there (open point 6).
- Memory: the rows and their absolute values are both kept (the approximations need products with |G|): 2 × 8 bytes per entry in float64, 2 × 4 in float32.

Target: the whole optimizer overhead of one outer iteration (screening, subproblem, updates) below **1 minute** for n = 10⁵ and |S| = 10⁴, below **10 minutes** for n = 10⁶ and |S| = 10⁴, on a 32-core machine — negligible next to 10⁴ rows costing one evaluation each.

### 3.8 Stopping

Any of:

- **Stalled**: at a feasible point, when the best KKT residual has not decreased by 10 % over `kkt_stall_iterations` iterations (10) while the iterates moved less than 1e-3 of the ranges — the status `stalled`, with the residual reached: the precision the problem allows, short of `kkt_tolerance`, instead of running to `max_iter`;
- **KKT**: feasibility `max(g) ≤ ineq_tolerance` and the KKT residual on S below `kkt_tolerance` (1e-3 by default, with `dual_tolerance` 1e-5 and `ineq_tolerance`, `eq_tolerance` 1e-5: the dual leaves a violation of the approximated constraints up to `dual_tolerance`, and feasibility cannot be asked tighter; the optimum to about 1e-3 on the variables and far better on the objective) — the projected gradient of the Lagrangian (gradients at x_k, multipliers of the subproblem that gave x_k; a variable within 10⁻⁸ of its range from a bound is at the bound) and the complementarity `max |λ_i g_i|`, both relative to the largest term of the gradient of the Lagrangian — a component of the gradient of the objective, or of a constraint times its multiplier — (never less than a thousandth of the gradient of the objective at the start, since it vanishes at an unconstrained optimum): a residual means the same whatever the units of the objective and of the constraints. Relative to the gradient of the objective alone, it read 0.6 on a small stress-constrained bracket (0.12 now) and 10 to 10⁶ through GEMSEO on the large one: a volume fraction has a gradient of 1/n per variable, the stresses of order 1. Near the optimum MMA may oscillate slightly (steep valleys, as Rosenbrock's): the residual then stalls around 10⁻⁴ and `xtol_rel` is the right stop;
- the relative change of f and of x over `stall_iterations` iterations below `ftol_rel` / `xtol_rel` — at a feasible point only;
- `max_iter` (outer iterations), `max_row_evaluations` (rows computed), GEMSEO's `max_time`;
- a stop requested by a listener (§ 5).

**Feasibility** (plan 69). MMA is not feasible at each iterate: on the stress-constrained bracket, the iterates kept 0.3 to 0.9 % above the stress limit near the reentrant corner until `max_iter`. Two mechanisms, with no setting to tune:

- **Path through the constraints** (`descent_iterations`, off by default; plan 74). From a neutral start, the run first goes down with soft constraints: the elastic variables cost a thousandth of `elastic_cost` (the objective dominates), for at most `descent_iterations` iterations, until the objective falls by less than 1 % in an iteration. The design ends near the lightest one, outside the constraints (for a structure, near the fully stressed design, every member at its limit); no stop criterion applies meanwhile, and the restoration below then brings it back at once, before the normal iterations. It needs no knowledge of the problem, only soft constraints. On the trusses, it makes GCMMA reach the 5060.85 lb optimum of the 10-bar truss instead of the local one, at more evaluations (71 against 41); it changes nothing on the 25- and 72-bar trusses, whose descent ends in 3 iterations.
- **Restoration**: an infeasible run whose objective has settled (it changed less than 10⁻³, relatively, over `kkt_stall_iterations` iterations), or `restoration_iterations` (20, a quarter of `max_iter` at most) away from `max_iter` — or from the end of a budget of evaluations, `max_evaluations`, at the rate of evaluations per iteration of the run (GEMSEO's `max_iter` counts evaluations: GCMMA makes about three per iteration, and a budget of 600 ended a piloted bracket at its iteration 212, long before the restoration planned for iteration 580; its iterates, converged at a volume of 0.346 just above the stress limit, left it with a feasible point of 0.509) —, is brought back within the constraints — and in these last iterations the moves shrink whether the point is feasible or not, or a full move would leave the constraints with no time to come back: GCMMA, a move limit halved at each iteration down to 10⁻³ of the ranges, the cost of the elastic variables ×10, and the dual solved to its finest tolerance — a tenth of the last step, the adaptive tolerance of § 3.7, left violations of 10⁻⁴ whatever the move limit. In the last iterations of the budget, the inequality constraints of the subproblem are instead tightened by 10⁻⁴ (on its scale of 1) and its dual solved to that tolerance: the approximated constraints end at most 0, for 6 to 9 times fewer dual evaluations and an objective larger by about 10⁻⁴ (at the finest tolerance, a restoration iteration of the bracket at 10⁴ elements took 478 s, 2,000 to 6,000 dual evaluations against 20 to 60 outside the restoration). Not in the middle of a run: iterates pushed off the active constraints by the margin alternated with the next iterations and kept the run from converging. L-BFGS-B keeps 100 pairs (10 by default), which halves the evaluations of these ill-conditioned duals. It ends when the point is feasible (the last iterations keep their small moves), or after `restoration_iterations` iterations. The iteration reports say how far a restoration has gone.
- **The best feasible point**: the result is the best feasible point met when the last one is infeasible or worse, with its iteration in the message. Without restoration, it may be an early, heavy design (the volume 0.69 of the second iteration, against 0.43 once restored, on a 20 × 20 bracket).

### 3.9 Colored sparse Jacobians

On large surfaces (hulls, car bodies, aircraft), a constraint depends on a few neighbouring variables: its row is sparse. The whole Jacobian then costs a few tens of **directional derivatives** instead of one gradient per constraint:

- **Pattern**: which variables each constraint depends on — a sparse boolean matrix (constraints × variables) given by the user's code, which knows the mesh (`sparsity()`, § 5; in GEMSEO, a step of the process called once with the variables and constraints as `(name, size)`, § 6). The optimizer needs no geometry. It must be sparse: a dense boolean matrix takes 10 GB at 10⁵ × 10⁵ and 1 TB at 10⁶ × 10⁶.
- **Coloring** (Curtis, Powell and Reid, 1974): a greedy coloring of the columns, largest degree first (a Numba loop: 5 s for two colorings of 10⁶ variables, once per run), so that no two variables of a color share a constraint. The number of colors is about the number of variables of a neighbourhood (13 at most for a 5-point 2D stencil), whatever the size of the problem.
- **Products**: one directional derivative per color, in the direction of the sum of its variables — by the tangent mode of the model (`directional_derivatives(x, directions)`, exact, in one parallel batch) or, when it has none, by forward finite differences on the values (a step of `difference_step` times the range, backwards at the upper bound; one evaluation per color). Each entry of a row is read in the product of its variable's color.
- **Updates**: between two colorings, Schubert's sparse quasi-Newton update corrects the Jacobian from the change of the constraint values over the step, with no evaluation; it is computed again every `jacobian_refresh` iterations.

**Optional, off by default.** `jacobian_mode` chooses how the rows are obtained: `rows` (§ 3.3–3.5, the default) or `hybrid`. `hybrid` is asked for explicitly — in GEMSEO Process Builder, a "Colored Jacobians" option of the driver, unchecked by default (§ 6): it asks more of the model (a pattern, a tangent mode or finite differences) and bets on the locality of the constraints, while the working set of rows runs on any model. It is refused without a pattern. A mode taking every row from the colored Jacobian (`colored`) was removed in plan 69, at the user's request: it converges to the optimum of the colored Jacobian and declares it, off wherever the constraints are not local — on the stress-constrained bracket, where 35 % of a stress row lies outside a pattern of one element, it could not even find a feasible design. **Without a pattern, the matrix is taken as full** and the optimizer runs without the sparse optimizations: coloring a full pattern would take one directional derivative per variable, worse than the rows of the working set.

**Approximate sparsity.** Mechanical constraints (the buckling of a panel, computed over 2 m of an 80 m hull) are mostly local but coupled to the whole structure through its state: their true Jacobian is dense, with entries decaying with the distance. In a colored product, the far entries of the variables of a color add to the near one: a small error on every colored entry. The colors therefore overlap, at the price of more directional derivatives:

- a **margin** (`pattern_margin`): the coloring is made on the pattern widened on itself — one widening adds to a constraint the variables of the constraints sharing a variable with it, no coordinates needed — so that the variables of a color are farther apart and leak less into each other;
- **several colorings** (`color_overlap`, 2 by default): each variable is in one color of each, with other companions; every entry is measured in several mixtures, recovered by least squares over the pattern, and the spread of its measures estimates its error (its leakage). Each coloring is valid on the pattern, so each reading is the entry plus what leaks into it: the least-squares estimate is the mean of the readings. **Each coloring is made on the pattern widened once more than the one before** (`pattern_margin`, then `pattern_margin + 1`…): colorings of the same widened pattern, even in other orders, come out nearly periodic on a regular stencil and leak the same far entries — their spread was correlated negatively with the true error over the rows (Spearman −0.66) —, while with a widening more each it follows it (+1.0 on a ring, +0.67 on a 2D grid, the median estimate within 5 % of the median error), and the entries are 30 % more accurate. The price is more colors: 25 and 53 on a 2D grid instead of 25 and 23.

The `hybrid` mode keeps the colored Jacobian for all the constraints and uses exact rows (the row cache, § 3.5) for those within `fresh_margin` of activity and for those whose estimated leakage exceeds `leakage_tolerance`: the constraints that decide the step are exact, the others only need to be roughly right to be screened and checked. `probe_sparsity` measures, at a point, the share of a few exact rows outside the pattern and the error of their colored entries, to choose the mode and the margin.

`hybrid` measures the KKT residual with the exact rows of the constraints near activity, the only ones with multipliers: its optimum is the problem's, whatever the leakage of the others. On the stress-constrained bracket, whose stresses depend on the whole structure through its displacements, every constraint of the working set leaks more than `leakage_tolerance`: `hybrid` asks for as many exact rows as the rows mode, and the colored Jacobian is a cost without benefit there (plan 69).

The colored Jacobian is not saved in the state (like the row cache): a resumed run colors again at its first iteration, exactly as the uninterrupted run with `jacobian_refresh` 1.

### 3.10 Relaxing constraints (continuation)

A converged run is at the best design its active constraints allow from where it started; the multipliers say what each constraint costs the objective (∂f*/∂b_i = −λ_i). `Optimizer.relax(indices, amount)` relaxes some inequality constraints to `g_i <= amount`, `Optimizer.tighten(factor)` multiplies the offsets by `factor` (0: the original constraints again; offsets under `ineq_tolerance` vanish). The state keeps the offsets `r_i` (`State.relaxation`, saved with it, so that a run resumed from a saved state goes on with the same relaxation) and the *effective* values `g_i − r_i` in `constraints`: the screening, the subproblem, the feasibility of the run, its restoration and its KKT residual are those of the relaxed problem, with no other change. What concerns the original problem reads the true values `g_i = effective + r_i`: the report (`max_constraint`, `violated`, `active`; `relaxed` counts the relaxed constraints), the best feasible point (a point feasible only when relaxed is never recorded) and the result.

A relaxation ends before the run does, so that the result is feasible for the original problem: `stop(when_feasible=True)` lifts it first, and the last iterations of the budget (§ 3.8) lift it before restoring feasibility. `relax_state` and `tighten_state` (`core/relaxation.py`) act on a saved state, for a pilot resuming a run that has ended.

## 4. Settings

A Pydantic model per algorithm (`LSO_MMA_Settings`, `LSO_GCMMA_Settings`), deriving from GEMSEO's `BaseOptimizerSettings`:

| Setting | Default | Meaning |
|---|---|---|
| `screening_margin`, `screening_margin_min`, `keep_factor` | 0.3, 0.05, 1.5 | δ_k, its floor, δ_keep = keep_factor × δ_k (§ 3.3) |
| `max_working_set` | 20,000 | Rows per iteration, at most |
| `max_screening_repairs` | 3 | § 3.2, step 5 |
| `violated_share`, `violated_working_set` | 0.25, 0.1 | § 3.3: the share of violated constraints above which the run is outside the feasible domain (1: never), and the share of the constraints its working set then holds |
| `row_refresh`, `fresh_margin`, `max_row_age`, `max_row_step` | `always`, 0.05, 3, 0.05 | § 3.5 |
| `asymptote_init`, `asymptote_increase`, `asymptote_decrease` | 0.5, 1.2, 0.7 | § 3.6 |
| `move_limit` | 0.5 | Fraction of the range |
| `elastic_cost` | 1000 | c_i (§ 3.6) |
| `dual_solver`, `dense_dual_threshold`, `dual_tolerance` | `auto`, 100, 1e-5 | § 3.7; `auto`: L-BFGS-B up to 10 constraints, the interior point up to `dense_dual_threshold` constraints (if n m² ≤ 10⁷), then Newton with sparse rows, L-BFGS-B with dense ones; the dual stops when the approximated constraints are met within `dual_tolerance` |
| `kkt_tolerance`, `stall_iterations` | 1e-3, 3 | § 3.8 |
| `row_dtype` | `float64` | The precision the rows are kept and multiplied in (§ 3.6); `float32` halves their memory, but its products (BLAS sums in float32, steps rounded to float32) put a rounding of about 10⁻¹⁰ in the dual value: its line searches stop 2·10⁻⁵ from the solution, above the finest tolerance of a restoration, which then ended infeasible |
| `elastic_quadratic`, `max_inner_iterations` | 1, 20 | Svanberg's d; GCMMA inner iterations per outer iteration |
| `max_row_evaluations` | none | Budget of rows |
| `row_batch_size` | none | Rows per request to the model (none: all at once) |
| `jacobian_mode` | `rows` | `rows` or `hybrid` (§ 3.9); `hybrid` only when asked for, and with a pattern |
| `descent_iterations` | 0 | The path through the constraints (§ 3.8; 0: off) |
| `restoration_iterations` | 20 | Iterations spent, at most, bringing an infeasible run back within the constraints (§ 3.8; 0: never) |
| `max_evaluations` | 0 | The evaluations a driver stops the run on, for the restoration before the end (§ 3.8); GEMSEO passes its `max_iter`; 0: none |
| `pattern_margin`, `color_overlap` | 1, 2 | Widenings of the pattern before coloring; colorings, each entry measured once per coloring (§ 3.9) |
| `leakage_tolerance` | 0.01 | `hybrid`: a constraint whose colored row has an estimated leakage above this share of its norm gets its exact row |
| `jacobian_refresh`, `difference_step` | 1, 1e-6 | Iterations between two colorings (Schubert updates in between); the step of the finite differences, relative to the ranges, without a tangent mode |

GEMSEO settings keep their meaning (`max_iter`, `ftol_rel`, `xtol_rel`, `ineq_tolerance`, `eq_tolerance`, `normalize_design_space`, `store_jacobian` forced to False: rows live in the cache, § 3.5).

## 5. Steppable core

The core (`gemseo_lso.core`) depends only on NumPy and SciPy. It sees the problem through a small protocol:

```python
class LargeScaleProblem(Protocol):
    x0: NDArray                                # starting point
    lower: NDArray; upper: NDArray             # finite bounds
    def values(self, x) -> tuple[float, NDArray, NDArray]:      # f, g (m,), h (p,)
    def objective_gradient(self, x) -> NDArray:                # (n,)
    def constraint_rows(self, x, rows: NDArray) -> NDArray | sparray:  # (len(rows), n)
    def equality_rows(self, x) -> NDArray | sparray:           # (p, n)
    # Optional (§ 3.9), absent or returning None when the model cannot:
    def sparsity(self) -> sparray | None:                      # (m, n), boolean
    def directional_derivatives(self, x, directions: sparray) -> NDArray | None:  # directions (n, k); (m, k)
```

and runs as a stepper:

```python
optimizer = Optimizer(problem, settings, state=None)  # or a saved state
for report in optimizer:  # one outer iteration per step
    ...  # read the report, change the settings, stop
# Restored exactly by Optimizer(..., state=State.load(path)).
optimizer.state.save(path)
```

- **Report** of an iteration: iterate index, f, max(g), number of violated and of active constraints, |S|, rows computed and reused, directional derivatives (`hybrid`), the iterations of a restoration of feasibility, the constraints relaxed (§ 3.10) and whether the iterate is outside the feasible domain (§ 3.3), screening repairs, GCMMA inner iterations, KKT residual, step norm, asymptote spread (quantiles), time spent in the model and in the optimizer.
- **State**: x_k, x_(k−1), x_(k−2), asymptotes, multipliers of S, the working set, the row cache (optional in a saved state: large), δ_k, iteration counters. Saved in HDF5 (`h5py`), never pickled.
- **Settings** can be replaced between two steps (`optimizer.settings = …`): no restart, nothing lost. In the core they are a frozen dataclass (`gemseo_lso.core.Settings`, NumPy and SciPy only); the GEMSEO settings models of § 4 map onto it (plan 68).
- **Stop**: `optimizer.stop(reason)` ends the loop cleanly after the current step.

## 6. GEMSEO integration

`gemseo_lso` is a GEMSEO plugin (entry point `gemseo_plugins`) with the algorithms `LSO_MMA` and `LSO_GCMMA` (a `BaseOptimizationLibrary`). It adapts an `OptimizationProblem` to the protocol of § 5:

- **Values**: through GEMSEO's functions, so the database, the listeners (and the Claude copilot) see every evaluation. GEMSEO's `max_iter` (it counts evaluations, finite differences and GCMMA inner iterations included) and `max_time` apply. `ftol_rel` and `xtol_rel` are the core's, over `stop_crit_n_x` outer iterations and at feasible points: GEMSEO's compare its last evaluations, and GCMMA's inner iterations and the repairs evaluate close points, taken for a stagnation — a piloted bracket stopped after 13 of its 160 iterations (volume 0.52 instead of 0.35). `ftol_abs` and `xtol_abs` are not used.
- **No Jacobian at the start**: GEMSEO evaluates every Jacobian at the starting point for the algorithms requiring gradients — 10¹⁰ entries at 10⁵ × 10⁵. The library declares `require_gradient` (the application shows it) and hides it while GEMSEO prepares the run; `store_jacobian` is forced to False.
- **Objective gradient**: `problem.objective.jac`.
- **Constraint rows**, two modes:
  - **Full Jacobian** (default): `constraint.jac(x)` gives the whole Jacobian (dense or sparse), the rows of S are taken from it. Right for small problems, for sparse explicit constraints, and for the validation against other optimizers. Costly when rows are expensive, since GEMSEO then computes them all.
  - **Row mode**: the discipline computing a constraint offers the rows on request, in one batch. GEMSEO differentiates whole outputs only (its `FunctionRestriction` restricts inputs, not output components), so the plugin defines an interface the model implements:

    ```python
    class RowJacobian(Protocol):
        def compute_jacobian_rows(
            self, output_name: str, rows: NDArray, input_data: Mapping[str, NDArray]
        ) -> Mapping[str, NDArray | sparray]:   # by input name: (len(rows), input size)
    ```

    The plugin chains these rows with the Jacobians of the design variables to the inputs of the discipline when there are intermediate disciplines (open point 5: coupled disciplines, where GEMSEO's adjoint would need a seed of selected rows).

    The row mode is used for every inequality constraint whose discipline offers `compute_jacobian_rows`; the others keep the full Jacobian. The plugin finds the disciplines of the problem through the adapters of its functions — a private attribute in GEMSEO 6.3, pinned by a test: without it, every constraint uses the full Jacobian — and the sign of a constraint written `g >= value` in its representation. GEMSEO linearizes a discipline for all its differentiated outputs at once: during the run, the outputs given row by row are removed from the differentiated outputs of their disciplines (and of the chains containing them), or the gradient of the objective would compute the whole Jacobian of the constraints. The constraints given row by row cannot be scaled (`scaling_threshold`).
- **Directional derivatives** (open point 7): a discipline may offer `compute_directional_derivatives(output_name, directions, input_data)`, the products of the Jacobian of an output with directions given by input name, `(input size, k)` each, returning `(output size, k)` (`TangentJacobian`); chained like the rows. When every inequality constraint has one, `hybrid` uses them; otherwise, finite differences on GEMSEO's values. GEMSEO's `JacobianOperator` was not used: a discipline builds it within `linearize`, for all its outputs at once, where the protocol asks for one output and a batch of directions.
- **Colored Jacobians** (§ 3.9), optional and off by default: `jacobian_mode` stays `rows` unless asked for; then the pattern comes from the setting `sparsity_pattern`, a function of the user's code (a step of the process) returning a sparse boolean matrix (constraints × variables). In GEMSEO Process Builder, the driver of an `LSO_*` algorithm has a "Colored Jacobians" checkbox, unchecked by default; checked, it shows the "Sparsity pattern" function, and the generated script passes `jacobian_mode="hybrid"` and `sparsity_pattern`; unchecked, neither is written.
- **Normalization**: rows are converted to the normalized design space (× the ranges).
- **Signs**: GEMSEO's `g ≤ 0` convention is kept; equality constraints as in § 3.4.
- In GEMSEO Process Builder: the algorithms appear with the others when the plugin is installed in the Python of the runs, and the algorithm explanations describe when to use them.

## 7. Performance and memory

| Item | n = 10⁵, |S| = 10⁴ | n = 10⁶, |S| = 10⁴ |
|---|---|---|
| Row cache (dense, float64) | 8 GB | 80 GB |
| One dual evaluation | ~10⁹ flops | ~10¹⁰ flops |
| Optimizer overhead per outer iteration (target) | < 1 min | < 10 min |
| Vectors of the state | a few MB | tens of MB |

- The optimizer never forms an n × n or an m × n dense matrix.
- The row request is the natural place for parallelism: the model receives all the rows of an iteration at once (or by `row_batch_size`) and may compute them on many cores or machines.
- The GEMSEO database keeps values only (`store_jacobian` False): for 10⁵ constraints, 0.8 MB per evaluation.

## 8. Piloting by Claude

The optimizer is designed for the copilot of `gemseo-claude-pilot` (docs/CLAUDE_PILOT_SPEC.md):

Implemented in plan 70 (docs/CLAUDE_PILOT_SPEC.md § 4.7):

- **Telemetry**: the report of § 5, given to the pilot at each outer iteration (an `algorithm_state` in its snapshot): `LSO_MMA` and `LSO_GCMMA` open a live run on their problem (`gemseo_lso.gemseo.live.live_run(problem)`) whose listeners get each report. The live run also moves the design (`move(x)`, GEMSEO's units, converted to the optimizer's space: `Optimizer.move` evaluates the point once and shifts the past iterates and the asymptotes with it, so that the asymptotes keep their spreads and their trend, the multipliers and the working set staying), and gives the multipliers of each inequality constraint at the last iteration (`multipliers()`, in the units of the objective per unit of the constraint: where a constraint costs most) and the projected gradient of the Lagrangian per design variable (`stationarity()`: where the KKT residual comes from); the pilot lays them on the grid of a design that describes its physics (plan 71, CLAUDE_PILOT_SPEC § 4.8).
- **Live settings**: a decision on `screening_margin`, `max_working_set`, `row_refresh` and its limits, the asymptote factors, `move_limit`, `elastic_cost` or the switch MMA ↔ GCMMA is applied **at the next outer iteration without a restart**: nothing is lost, unlike the segments of other algorithms. Every setting of the core can change live but those GEMSEO owns or checks the result with (`method`, `max_iter`, `ftol_rel`, `xtol_rel`, `stall_iterations`, `ineq_tolerance`, `eq_tolerance`) and `jacobian_mode`; a change is checked against the ranges and cross checks of the settings, and refused whole if one fails. A switch back to MMA also clears the automatic switch to GCMMA.
- **Relaxation**: `LiveRun.relax({constraint: indices}, amount)` and `tighten(factor)`, applied at the next outer iteration after the states asked for (a checkpoint is the state before the relaxation), and `relaxation()` (the offsets); `multipliers()` gives what each constraint costs (§ 3.10).
- **Detectors** for this optimizer: screening repairs at every iteration (margin too small), a working set that churns (hysteresis too small), oscillating asymptotes (decrease factor), many GCMMA inner iterations (approximations too loose), rows mostly reused and repairs rising (stale rows hurting), a budget of rows running out.
- **Restart across processes**: the saved state (§ 5) lets a run stopped by the user or by a crash resume exactly: the setting `save_state` writes it at the end of a run (a stopped one included), `resume_from` starts from it (the run goes on at its iterate, with its asymptotes and multipliers; with `row_refresh` `always`, it ends at the same iterate as the uninterrupted run — test); the live run saves it on request. The live run stops on request (`stop(reason, when_feasible=False)`; with `when_feasible`, an infeasible iterate is first brought back within the constraints, for at most `restoration_iterations` iterations, and the run ends there: `Optimizer.stop(when_feasible=True)`). It also brings the iterate back within the constraints on request (`restore_feasibility()`: the restoration of § 3.8 starts at the next iteration instead of near the end of the budget or once the objective has settled; `Optimizer.restore_feasibility`), and a pilot learns of a run when it opens (`on_open(problem, callback)`), before any point is announced.
- **A budget of rows**: `max_row_evaluations` stops the run with the status `max_rows` once that many constraint gradients were asked for (0: none).

## 9. Validation

- **Small problems**, against published results and other optimizers of GEMSEO: Svanberg's two-variable example and cantilever beam (1987), Hock–Schittkowski problems with inequality constraints, constrained Rosenbrock; the same optimum as `NLOPT_MMA` (MMA) and `SLSQP` within tolerance.
- **Screening**: on a problem whose active set is known, the same optimum with screening as without (`max_working_set` = m), with fewer rows.
- **Large synthetic problems**: a separable quadratic objective with 10⁵ and 10⁶ local constraints and a known solution — correctness, rows per iteration, optimizer time, memory.
- **Realistic benchmark**: stress-constrained topology optimization in 2D (plane stress finite elements in `scipy.sparse`, a density per element, a relaxed von Mises constraint per element), written in the plugin's benchmarks: 10⁴ to 10⁵ elements, rows by adjoint with a reused factorization. It is the classic problem of this size and structure.
- **Literature** (plan 74, `benchmarks/run_literature.py`, tests in `tests/test_lso_literature.py`): the 10-, 25- and 72-bar trusses (Schmit and Farshi, and successors: 5060.85, 545.16 and 379.62 lb, geometry rebuilt and checked against the published designs), Svanberg's beam (closed-form optimum, 5 to 10⁴ segments), Hock–Schittkowski 71, 100 and 113, SLSQP as an independent reference. MMA reaches every published optimum to 10⁻⁴ or better in at most 30 iterations on the trusses and the Hock–Schittkowski problems; the beam converges to its analytic optimum up to 10⁴ segments (GCMMA: 35 iterations, 0.4 s). What they showed: silent L-BFGS-B and interior-point failures and a warning from the reduced system (fixed, § 3.7), and a poor automatic dual solver for many variables and one constraint (rule of `dual_solver="auto"`, § 3.7). Known limits, not fixed: MMA is sensitive to the width of the variable bounds (a factor 100 on the beam does not converge in 300 iterations; 10⁵ segments with common bounds stall at a KKT residual of 0.9); GCMMA lands in the 5076.85 lb local optimum of the 10-bar truss from most starts (MMA, in the 5060.85 lb one); the interior point is slow on hard subproblems of few variables (8 s for MMA on the beam of 100 segments); `dual_solver="newton"` chosen explicitly on a dense problem with one constraint returns the bounds silently.
- Tests: none over one second (the rule of the repository); the large runs are benchmarks, outside the test suite, with their results recorded.

## 10. Later modes

- **Weighted adjoint** (matrix-free): a model giving Jᵀw in one solve allows an augmented Lagrangian on all the constraints with one gradient per iteration.
- **Second-order information**: an L-BFGS curvature term in the approximations (MMA with quasi-Newton corrections) to converge in fewer iterations near the optimum.
- **Aggregated constraints** by zones (KS or p-norm) as a first phase before the exact local constraints.

## 11. Package, dependencies, licenses

```
plugins/gemseo_lso/
  pyproject.toml, LICENSE (MIT), README.md
  src/gemseo_lso/
    core/ (problem protocol, MMA, GCMMA, subproblem duals, screening, row cache, state, report)
    gemseo/ (library, settings, problem adapter, RowJacobian protocol)
  tests/, benchmarks/
```

Dependencies: `numpy`, `scipy` (BSD), `h5py` (BSD), `numba` (BSD-2-Clause, with `llvmlite`: BSD-2-Clause and Apache-2.0 with the LLVM exception; § 3.7), `pydantic` (MIT), `gemseo` (LGPL, imported only). The methods are written from the papers of Svanberg; no code is taken from other implementations.

## 12. Proposed plans

| # | Title | Content |
|---|---|---|
| 65 | Core MMA and GCMMA | Protocol, approximations, asymptotes, dual solver, stepper, state, report; small problems against published results and `NLOPT_MMA` |
| 66 | Screening and row cache | Working set, screening check and repairs, stale rows, equality pairs; the screening tests and the large synthetic problems |
| 67 | Colored sparse Jacobians | Pattern, coloring, directional derivatives (tangent mode) or finite differences, Schubert updates, the `hybrid` mode (`colored` removed in plan 69), `probe_sparsity` |
| 68 | GEMSEO plugin | Library, settings, full-Jacobian mode, row mode, hybrid mode (directional derivatives through GEMSEO), normalization; listed in the application with its explanation |
| 69 | Benchmarks | Topology optimization with stress constraints, 10⁴ to 10⁵ elements; the working set against the hybrid Jacobians; measured evaluations, time and memory; feasibility (restoration, best feasible point); tuning of the defaults |
| 70 | Piloting by Claude | Telemetry, live settings, detectors, prompt; state saved and resumed |

They replace the drafts of plans 65 and 66 for an IPOPT plugin, which did not fit the cost of the gradients.

## 13. Open points

| # | Topic | Action |
|---|---|---|
| 1 | Name of the package and of the algorithms | Decide before plan 65 |
| 2 | Convergence with stale rows (`near_active`) | Measure on the benchmarks; keep `always` as the default until then |
| 3 | Scaling of the constraints (screening in their units) | Settled: the subproblem and the screening scale them from their rows (§ 3.3, § 3.6) |
| 4 | Weighted adjoint mode | Later (§ 10) |
| 5 | Rows through coupled disciplines (an MDA): GEMSEO's adjoint seeded with selected rows | Prototyped in plan 68: `JacobianAssembly.coupled_system.adjoint_mode` accepts the rows of ∂g/∂x and ∂g/∂y as its seeds and gives exactly those rows of the coupled total derivatives (Sellar with vector couplings, rows 1 and 4 of 6: identical), one adjoint solve per row; the Jacobians of the coupled disciplines themselves are still computed in full. First version: row mode on a single discipline or an uncoupled chain, a coupled one refused with a message |
| 6 | Dual solver accuracy (L-BFGS-B) for the multipliers used by screening and KKT | Compare with the interior-point subsolver on the benchmarks |
| 7 | Directional derivatives through GEMSEO: its `JacobianOperator` products, or a protocol on the discipline like `RowJacobian` | Settled in plan 68: the `TangentJacobian` protocol on the discipline (§ 6); finite differences otherwise |
