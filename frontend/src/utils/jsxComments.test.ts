import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import JsxParser from 'react-jsx-parser'
import { extractJsxAndBindings, stripJsxComments } from './jsxPreambleParser'

function render(source: string): { html: string; errors: string[] } {
  const { jsx, bindings } = extractJsxAndBindings(source)
  const errors: string[] = []
  const html = renderToStaticMarkup(
    createElement(JsxParser, { jsx, bindings, renderInWrapper: false, onError: (e: Error) => errors.push(e.message) })
  )
  return { html, errors }
}

describe('JSX comment-only brace groups (JSXEmptyExpression)', () => {
  it('the raw parser really does fail on a comment brace group (documents the bug)', () => {
    const errors: string[] = []
    renderToStaticMarkup(
      createElement(JsxParser, { jsx: '<div>{/* note */}<p>x</p></div>', renderInWrapper: false, onError: (e: Error) => errors.push(e.message) })
    )
    expect(errors.join(' ')).toMatch(/JSXEmptyExpression/)
  })

  it('renders a dashboard with block comments between charts', () => {
    const { html, errors } = render(`<div>
  {/* Revenue chart */}
  <section><p>a</p></section>
  {/* Cost chart */}
  <section><p>b</p></section>
</div>`)
    expect(errors).toEqual([])
    expect(html).toContain('<p>a</p>')
    expect(html).toContain('<p>b</p>')
    expect(html).not.toContain('Revenue chart')
  })

  it('handles line comments, multiple comments in one group, and multi-line block comments', () => {
    const { html, errors } = render(`<div>{ // one
  }<p>x</p>{/* a */ /* b */}<p>y</p>{/*
   multi
   line
*/}</div>`)
    expect(errors).toEqual([])
    expect(html).toBe('<div><p>x</p><p>y</p></div>')
  })

  it('leaves real expressions and empty object literals in attributes alone', () => {
    expect(stripJsxComments('<div style={{}} data={[{}]}>{value}</div>')).toBe('<div style={{}} data={[{}]}>{value}</div>')
    expect(stripJsxComments('<p>{ "a /* not a comment */ b" }</p>')).toBe('<p>{ "a /* not a comment */ b" }</p>')
  })

  it('works with a preamble of bindings too', () => {
    const { html, errors } = render(`const title = "T";
<div>{/* header */}<h1>{title}</h1></div>`)
    expect(errors).toEqual([])
    expect(html).toBe('<div><h1>T</h1></div>')
  })
})
