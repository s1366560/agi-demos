import { render } from '@testing-library/react'

import { MaterialIcon } from './src/components/agent/shared/MaterialIcon'

const { container } = render(
  <MaterialIcon
    name="search"
    size={20}
    style={{ color: 'blue', margin: '10px' }}
  />
)

const icon = container.querySelector('.material-symbols-outlined')
console.log('Icon:', icon)
console.log('Style attribute:', icon?.getAttribute('style'))
console.log('Style property:', icon?.style)
console.log('fontSize:', icon?.style.fontSize)
console.log('color:', icon?.style.color)
console.log('margin:', icon?.style.margin)
