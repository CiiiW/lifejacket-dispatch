/**
 * A report's status in words for the person who filed it.
 *
 * Not the console's labels: "awaiting_dispatch" means nothing on a beach.
 */

export type StatusTone = 'draft' | 'active' | 'closed';

export function reportStatus(status: string | undefined, complete: boolean | undefined) {
  switch (status) {
    case 'awaiting_dispatch':
      return { label: 'Received', tone: 'active' as StatusTone };
    case 'dispatched':
      return { label: 'Sent to a rescue team', tone: 'active' as StatusTone };
    case 'accepted':
      return { label: 'Team accepted', tone: 'active' as StatusTone };
    case 'en_route':
      return { label: 'Team on the way', tone: 'active' as StatusTone };
    case 'on_scene':
      return { label: 'Team on scene', tone: 'active' as StatusTone };
    case 'guidance_only':
      return { label: 'No rescue needed', tone: 'closed' as StatusTone };
    case 'resolved':
    case 'cancelled':
      return { label: 'Closed', tone: 'closed' as StatusTone };
    default:
      return complete
        ? { label: 'Received', tone: 'active' as StatusTone }
        : { label: 'Not sent yet', tone: 'draft' as StatusTone };
  }
}

/** "Nov 25, 3:42 PM". */
export function shortWhen(iso: string): string {
  const date = new Date(iso);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const hours = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${months[date.getMonth()]} ${date.getDate()}, ${hours % 12 || 12}:${minutes} ${hours < 12 ? 'AM' : 'PM'}`;
}
