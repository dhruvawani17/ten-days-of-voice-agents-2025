import * as React from 'react';
import { cn } from '@/lib/utils';

export interface ChatEntryProps extends React.HTMLAttributes<HTMLLIElement> {
  /** The locale to use for the timestamp. */
  locale: string;
  /** The timestamp of the message. */
  timestamp: number;
  /** The message to display. */
  message: string;
  /** The origin of the message. */
  messageOrigin: 'local' | 'remote';
  /** The sender's name. */
  name?: string;
  /** Whether the message has been edited. */
  hasBeenEdited?: boolean;
}

export const ChatEntry = ({
  name,
  locale,
  timestamp,
  message,
  messageOrigin,
  hasBeenEdited = false,
  className,
  ...props
}: ChatEntryProps) => {
  const time = new Date(timestamp);
  const title = time.toLocaleTimeString(locale, { timeStyle: 'full' });
  const isOrderSummary = /^order summary:/i.test(message.trim());
  const summaryBody = isOrderSummary ? message.replace(/^order summary:/i, '').trim() : message;

  return (
    <li
      title={title}
      data-lk-message-origin={messageOrigin}
      className={cn('group flex w-full flex-col gap-0.5', className)}
      {...props}
    >
      <header
        className={cn(
          'text-muted-foreground flex items-center gap-2 text-sm',
          messageOrigin === 'local' ? 'flex-row-reverse' : 'text-left'
        )}
      >
        {name && <strong>{name}</strong>}
        <span className="font-mono text-xs opacity-0 transition-opacity ease-linear group-hover:opacity-100">
          {hasBeenEdited && '*'}
          {time.toLocaleTimeString(locale, { timeStyle: 'short' })}
        </span>
      </header>
      <span
        className={cn(
          'max-w-[80%] rounded-[20px] text-sm leading-relaxed',
          messageOrigin === 'local'
            ? 'bg-muted ml-auto p-2'
            : isOrderSummary
              ? 'mr-auto block rounded-2xl border border-amber-200 bg-amber-50/90 p-3 text-amber-900 shadow-sm'
              : 'mr-auto'
        )}
      >
        {isOrderSummary ? (
          <>
            <p className="font-semibold uppercase tracking-wide text-xs text-amber-700">Order summary</p>
            <p className="mt-1 text-base font-medium text-amber-900">{summaryBody}</p>
          </>
        ) : (
          message
        )}
      </span>
    </li>
  );
};
