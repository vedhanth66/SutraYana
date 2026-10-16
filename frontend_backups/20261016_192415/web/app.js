const planList = document.getElementById('planList');
const planTitle = document.getElementById('planTitle');
const roomCount = document.getElementById('roomCount');
const sourceLabel = document.getElementById('sourceLabel');
const provenanceLabel = document.getElementById('provenanceLabel');
const summaryPanel = document.getElementById('summaryPanel');
const warningList = document.getElementById('warningList');
const refreshBtn = document.getElementById('refreshBtn');
const solveBtn = document.getElementById('solveBtn');

let plans = [];
let activeKey = null;

async function loadPlans() {
  const res = await fetch('/api/plans');
  const data = await res.json();
  plans = Array.isArray(data) ? data : [];
  renderPlanList();

  if (!activeKey && plans.length) {
    selectPlan(plans[0].key);
  }
}

function renderPlanList() {
  if (!planList) return;
  planList.innerHTML = '';

  plans.forEach((plan) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'plan-item' + (plan.key === activeKey ? ' selected' : '');
    button.textContent = `${plan.name} (${plan.rooms} rooms)`;
    button.addEventListener('click', () => selectPlan(plan.key));
    planList.appendChild(button);
  });
}

async function selectPlan(key) {
  activeKey = key;
  renderPlanList();

  const response = await fetch(`/api/plan/${key}`);
  const plan = await response.json();

  planTitle.textContent = plan.id || 'Plan';
  roomCount.textContent = (plan.rooms || []).length;
  sourceLabel.textContent = plan.provenance || '—';
  provenanceLabel.textContent = plan.provenance || '—';
  summaryPanel.textContent = JSON.stringify({
    id: plan.id,
    bounds: plan.bounds,
    roomCount: (plan.rooms || []).length,
    warnings: (plan.warnings || []).length,
    links: (plan.links || []).length,
    provenance: plan.provenance,
  }, null, 2);

  const warnings = Array.isArray(plan.warnings) ? plan.warnings : [];
  warningList.innerHTML = '';
  if (!warnings.length) {
    const item = document.createElement('li');
    item.textContent = 'No warnings.';
    warningList.appendChild(item);
    return;
  }

  warnings.forEach((warning) => {
    const item = document.createElement('li');
    item.textContent = warning.message || JSON.stringify(warning);
    warningList.appendChild(item);
  });
}

async function solveSelectedPlan() {
  if (!activeKey) return;
  const payload = {
    key: activeKey,
    wire_clearance: 0.5,
    timeout: 30,
    enhanced: false,
  };

  const response = await fetch('/api/solve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  const result = await response.json();
  if (result.error) {
    summaryPanel.textContent = `Solve failed: ${result.error}`;
    return;
  }

  const jobId = result.job_id;
  summaryPanel.textContent = `Solve started. Job id: ${jobId}`;
  pollJob(jobId);
}

async function pollJob(jobId) {
  const response = await fetch(`/api/jobs/${jobId}`);
  const job = await response.json();

  if (job.status === 'running') {
    setTimeout(() => pollJob(jobId), 1000);
    return;
  }

  if (!job.ok) {
    summaryPanel.textContent = `Job finished with error: ${job.error || 'Unknown error'}`;
    return;
  }

  summaryPanel.textContent = JSON.stringify(job, null, 2);
}

refreshBtn.addEventListener('click', loadPlans);
solveBtn.addEventListener('click', solveSelectedPlan);

loadPlans();
