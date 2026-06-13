import { useEffect, useRef, useState } from 'react';

interface FlashCellProps {
  value: number;
  format?: (val: number) => string;
  className?: string;
  style?: React.CSSProperties;
}

export const FlashCell = ({ value, format, className = '', style }: FlashCellProps) => {
  const prevValueRef = useRef<number>(value);
  const [flashClass, setFlashClass] = useState<string>('');

  useEffect(() => {
    const prev = prevValueRef.current;
    if (value > prev) {
      setFlashClass('flash-up');
    } else if (value < prev) {
      setFlashClass('flash-down');
    }
    prevValueRef.current = value;

    const timer = setTimeout(() => {
      setFlashClass('');
    }, 600);

    return () => clearTimeout(timer);
  }, [value]);

  const displayValue = format ? format(value) : value.toString();

  return (
    <span className={`${flashClass} ${className}`} style={{ transition: 'background-color 0.2s', padding: '1px 3px', borderRadius: '2px', ...style }}>
      {displayValue}
    </span>
  );
};
