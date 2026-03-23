// ============================================
// Safe DOM helpers — prevents innerHTML XSS sinks
//
// All data-driven rendering should use these helpers
// instead of raw .innerHTML with string interpolation.
// ============================================

/**
 * Set element text safely (uses textContent, not innerHTML).
 * @param {Element} el
 * @param {string|number} text
 */
function setText(el, text) {
  if (el) el.textContent = text == null ? '' : String(text);
}

/**
 * Create an element with optional attributes and children.
 * @param {string} tag - HTML tag name
 * @param {Object} [attrs] - attributes/properties to set
 * @param {Array<Node|string>} [children] - child nodes or text strings
 * @returns {Element}
 *
 * Special attrs:
 *   style: object of CSS properties (camelCase keys)
 *   className: sets class attribute
 *   dataset: object of data-* attributes
 *   on*: event listeners (e.g. onclick)
 *   _html: sets innerHTML for trusted static markup (SVG, gauges)
 */
function h(tag, attrs, children) {
  var el = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function(key) {
      var val = attrs[key];
      if (key === 'style' && typeof val === 'object') {
        Object.keys(val).forEach(function(p) { el.style[p] = val[p]; });
      } else if (key === 'className') {
        el.className = val;
      } else if (key === 'dataset') {
        Object.keys(val).forEach(function(k) { el.dataset[k] = val[k]; });
      } else if (key.indexOf('on') === 0) {
        el.addEventListener(key.slice(2).toLowerCase(), val);
      } else if (key === '_html') {
        el.innerHTML = val; // trusted markup only
      } else {
        el.setAttribute(key, val);
      }
    });
  }
  if (children) {
    children.forEach(function(child) {
      if (child == null) return;
      if (typeof child === 'string' || typeof child === 'number') {
        el.appendChild(document.createTextNode(String(child)));
      } else {
        el.appendChild(child);
      }
    });
  }
  return el;
}

/**
 * Clear an element and append new children.
 * @param {Element} el - container to clear
 * @param {Array<Node>} nodes - new child nodes
 */
function replaceChildren(el, nodes) {
  if (!el) return;
  el.textContent = '';
  nodes.forEach(function(node) {
    if (node != null) el.appendChild(node);
  });
}

/**
 * Render a list of items into a container using a render function.
 * @param {Element} el - container element
 * @param {Array} items - data items
 * @param {Function} renderItem - function(item, index) => Node
 */
function renderList(el, items, renderItem) {
  if (!el) return;
  el.textContent = '';
  items.forEach(function(item, i) {
    var node = renderItem(item, i);
    if (node) el.appendChild(node);
  });
}

/**
 * Set trusted innerHTML on an element (for static SVG/gauge markup).
 * Equivalent to el.innerHTML = html but signals intent in code review.
 * @param {Element} el
 * @param {string} html - trusted static markup
 */
function setTrustedHTML(el, html) {
  if (el) el.innerHTML = html; // trusted markup only
}

/**
 * Create a text node.
 * @param {string} text
 * @returns {Text}
 */
function textNode(text) {
  return document.createTextNode(text == null ? '' : String(text));
}
