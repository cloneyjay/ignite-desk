with open('frontend/src/pages/AgentWorkbench.tsx', 'r') as f:
    content = f.read()

# Fix the account type to accept null
content = content.replace(
    'account: { equity: number; profit: number; server: string; currency: string; margin_free: number; mode: "demo" | "live" } | undefined;',
    'account: { equity: number; profit: number; server: string; currency: string; margin_free: number; mode: "demo" | "live" } | undefined | null;'
)

# Fix the risk type to accept null
content = content.replace(
    'risk: { open_risk_usd: number; open_risk_pct: number; cap_pct: number; daily_pnl: number; daily_loss_limit_pct: number } | undefined;',
    'risk: { open_risk_usd: number; open_risk_pct: number; cap_pct: number; daily_pnl: number; daily_loss_limit_pct: number } | undefined | null;'
)

with open('frontend/src/pages/AgentWorkbench.tsx', 'w') as f:
    f.write(content)

print('Done')