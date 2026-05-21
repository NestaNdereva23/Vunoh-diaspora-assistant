// dashboard.js — handles task submission and status updates

// ── Character counter ──────────────────────────────────────────
const messageInput = document.getElementById('messageInput');
const charCount    = document.getElementById('charCount');

messageInput.addEventListener('input', () => {
  charCount.textContent = `${messageInput.value.length} / 1000`;
});

// ── Task submission ────────────────────────────────────────────
const submitBtn     = document.getElementById('submitBtn');
const submitLabel   = document.getElementById('submitLabel');
const submitSpinner = document.getElementById('submitSpinner');
const submitResult  = document.getElementById('submitResult');

submitBtn.addEventListener('click', async () => {
  const message = messageInput.value.trim();

  if (!message) {
    messageInput.focus();
    return;
  }

  // Loading state
  submitBtn.disabled = true;
  hide(submitLabel);
  show(submitSpinner);
  hide(submitResult);

  try {
    const response = await fetch('/tasks/submit/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ message }),
    });

    const data = await response.json();

    if (!response.ok) {
      showResultError(data.error || 'Something went wrong. Please try again.');
      return;
    }

    showResultSuccess(data);

    // Reset form
    messageInput.value = '';
    charCount.textContent = '0 / 1000';

    // Reload the page after a short delay so the new task appears in the grid
    
    if (data.task_code) {
    fetch('/')  
    .then(r => r.text())
    .then(html => {
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const newCards = doc.querySelectorAll('.task-card');
      const existingIds = new Set();
      document.querySelectorAll('.task-card').forEach(c => existingIds.add(c.dataset.taskId));
      
      newCards.forEach(card => {
        if (!existingIds.has(card.dataset.taskId)) {
          document.getElementById('taskGrid')?.prepend(card);
        }
      });
    });
}

  } catch (err) {
    showResultError('Could not reach the server. Please check your connection.');
  } finally {
    submitBtn.disabled = false;
    show(submitLabel);
    hide(submitSpinner);
  }
});

function showResultSuccess(task) {
  submitResult.innerHTML = `
    <span class="result-code">${task.task_code}</span>
    <div class="result-row">Your request has been received and assigned to the <strong>${task.assigned_team}</strong> team.</div>
    <div class="result-row">Risk level: <strong>${task.risk_label} (${task.risk_score}/100)</strong></div>
    <div class="result-row">Status: <strong>${task.status}</strong></div>
  `;
  submitResult.style.borderColor = 'var(--green-400)';
  show(submitResult);
}

function showResultError(message) {
  submitResult.innerHTML = `<span style="color:var(--amber)">⚠ ${message}</span>`;
  submitResult.style.borderColor = 'var(--amber)';
  show(submitResult);
}

// Status update
async function updateStatus(selectEl) {
  const taskId   = selectEl.dataset.taskId;
  const newStatus = selectEl.value;

  // Optimistically update the badge while the request is in flight
  const card  = document.getElementById(`assistant-${taskId}`);
  const badge = card.querySelector('.badge');
  setBadge(badge, newStatus);

  try {
    const response = await fetch(`/assistant/${taskId}/status/`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ status: newStatus }),
    });

    if (!response.ok) {
      // Revert the badge if the server rejected the change
      const original = selectEl.dataset.originalStatus || newStatus;
      setBadge(badge, original);
      console.error('Status update failed:', await response.json());
    } else {
      // Persist the new value so we can revert correctly on future failures
      selectEl.dataset.originalStatus = newStatus;
    }

  } catch (err) {
    console.error('Network error on status update:', err);
  }
}

function setBadge(badge, status) {
  const classMap = {
    'Pending':     'badge--pending',
    'In Progress': 'badge--inprogress',
    'Completed':   'badge--completed',
  };
  badge.className = 'badge';
  badge.classList.add(classMap[status] || 'badge--pending');
  badge.textContent = status;
}

// Store original status on each select for revert support
document.querySelectorAll('.status-select').forEach(sel => {
  sel.dataset.originalStatus = sel.value;
});