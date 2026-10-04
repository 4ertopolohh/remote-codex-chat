import styles from './SelectControl.module.scss'

type Option = { value: string; label: string }

type Props = {
  label: string
  value: string
  options: Option[]
  disabled: boolean
  onChange: (value: string) => void
  className?: string
}

export function SelectControl({ label, value, options, disabled, onChange, className }: Props) {
  return <label className={`${styles.control} ${className ?? ''}`}>{label}
    <select value={value} disabled={disabled} onChange={event => onChange(event.target.value)}>
      {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  </label>
}
