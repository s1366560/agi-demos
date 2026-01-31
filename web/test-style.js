// Test to understand style merging
const props = { style: { color: 'blue', margin: '10px' } };
const size = 20;

const result = {
  fontVariationSettings: '0 400 0 24',
  fontSize: `${size}px`,
  lineHeight: '1',
  ...props.style,
};

console.log('Result:', result);
