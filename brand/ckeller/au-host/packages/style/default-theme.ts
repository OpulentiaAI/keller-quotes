// Shipped visual policy belongs to the style package. Existing device choices take precedence.
import palette from './themes/ckeller.theme.css?raw'
import finish from './themes/flat-surfaces.css?raw'
export const defaultTheme = {
  id: 'shipped:ckeller-flat',
  name: 'CKeller — Flat',
  css: `${palette}\n${finish}`,
}
