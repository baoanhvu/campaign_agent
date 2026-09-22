/* Admin page JS — prompt editing, quality dashboard */
async function loadAdminData() {
  const token = localStorage.getItem('admin_token') || '';
  try {
    const [prompts, quality] = await Promise.all([
      fetch('/api/admin/prompts', { headers: { 'X-Admin-Token': token } }).then(r => r.json()),
      fetch('/api/admin/quality', { headers: { 'X-Admin-Token': token } }).then(r => r.json()),
    ]);
    console.log('Prompts:', prompts);
    console.log('Quality:', quality);
  } catch (e) {
    console.error('Admin load failed', e);
  }
}

async function savePrompt(name, system, template) {
  const token = localStorage.getItem('admin_token') || '';
  await fetch(`/api/admin/prompts/${name}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': token },
    body: JSON.stringify({ system, template }),
  });
}
