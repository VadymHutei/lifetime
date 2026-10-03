/* Progressive enhancement: return keyboard focus to the result after a POST. */
(() => {
  const select = document.getElementById('country');
  if (select) {
    const options = Array.from(select.options, option => option.cloneNode(true));
    const wrapper = document.createElement('div');
    wrapper.className = 'location-filter';
    const label = document.createElement('label');
    label.htmlFor = 'location-filter';
    label.textContent = select.dataset.searchLabel;
    const input = document.createElement('input');
    input.type = 'search';
    input.id = 'location-filter';
    input.autocomplete = 'off';
    wrapper.append(label, input);
    select.before(wrapper);
    input.addEventListener('input', () => {
      const value = select.value;
      const query = input.value.trim().toLocaleLowerCase();
      select.replaceChildren(...options.filter(option =>
        option.value === value || !option.value || option.textContent.toLocaleLowerCase().includes(query)
      ).map(option => option.cloneNode(true)));
      select.value = value;
    });
  }
  const result = document.getElementById('result');
  if (result) {
    result.setAttribute('tabindex', '-1');
    // The rendered result remains fully available without JavaScript.
    result.focus({ preventScroll: true });
  }
})();
