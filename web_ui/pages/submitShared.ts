import { SubmitQueueStartBlockedItem, SubmitQueueStartResponse } from '../api';

export function formatBlockedItem(item: SubmitQueueStartBlockedItem): string {
  const fixedText = (item.auto_fixed_actions && item.auto_fixed_actions.length)
    ? `，已自动修复: ${item.auto_fixed_actions.join('、')}`
    : '';
  const remain = (item.remaining_blockers || []).slice(0, 2).join('；');
  return `拦截 ${item.project_name}(score=${item.score})${fixedText}${remain ? `，剩余: ${remain}` : ''}`;
}

export function buildSubmitStartAlert(result: SubmitQueueStartResponse, maxItems: number = 3): string {
  let detail = `提交任务已启动（可提交 ${result.eligible}，拦截 ${result.blocked}）`;
  if (result.blocked_items?.length) {
    const lines = result.blocked_items.slice(0, maxItems).map((item) => `- ${formatBlockedItem(item)}`);
    detail += `\n${lines.join('\n')}`;
  }
  return detail;
}
