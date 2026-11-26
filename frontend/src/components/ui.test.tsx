import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Button, ConfirmButton, Dialog, Segmented, Switch } from './ui'

afterEach(cleanup)

describe('ui', () => {
  it('Button shows its cost and blocks clicks while busy', () => {
    const onClick = vi.fn()
    const { rerender } = render(<Button cost={0.04} onClick={onClick}>Make picture</Button>)
    expect(screen.getByRole('button').textContent).toContain('$0.040')
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledTimes(1)
    rerender(<Button busy onClick={onClick}>Make picture</Button>)
    expect((screen.getByRole('button') as HTMLButtonElement).disabled).toBe(true)
  })

  it('Button says when a price is unknown', () => {
    render(<Button cost="unknown">Go</Button>)
    expect(screen.getByRole('button').textContent).toContain('price unknown')
  })

  it('ConfirmButton asks twice before deleting', () => {
    const onConfirm = vi.fn()
    render(<ConfirmButton label="Delete shot 1" onConfirm={onConfirm} />)
    fireEvent.click(screen.getByRole('button', { name: /Delete shot 1/ }))
    expect(onConfirm).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Keep it' }))
    expect(onConfirm).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /Delete shot 1/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Yes, delete' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('Segmented and Switch expose their state to assistive tech', () => {
    const onChange = vi.fn()
    render(<><Segmented label="Shape" value="9:16" onChange={onChange} options={[{ value: '9:16', label: '9:16' }, { value: '1:1', label: '1:1' }]} /><Switch checked={false} label="Captions" onChange={onChange} /></>)
    expect(screen.getByRole('radio', { name: '9:16' }).getAttribute('aria-checked')).toBe('true')
    fireEvent.click(screen.getByRole('radio', { name: '1:1' }))
    expect(onChange).toHaveBeenCalledWith('1:1')
    expect(screen.getByRole('switch', { name: 'Captions' }).getAttribute('aria-checked')).toBe('false')
    fireEvent.click(screen.getByRole('switch', { name: 'Captions' }))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('Dialog closes on Escape and labels itself', () => {
    const onClose = vi.fn()
    render(<Dialog open onClose={onClose} title="New brand"><input aria-label="Name" /></Dialog>)
    expect(screen.getByRole('dialog', { name: 'New brand' })).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })
})
