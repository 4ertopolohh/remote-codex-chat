import type { ButtonHTMLAttributes } from 'react'
import styles from './ActionButton.module.scss'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { tone?: 'primary' | 'secondary' }

export function ActionButton({ tone = 'primary', className, type = 'button', ...props }: Props) {
  return <button {...props} type={type} className={`${styles.button} ${tone === 'secondary' ? styles.secondary : ''} ${className ?? ''}`} />
}
