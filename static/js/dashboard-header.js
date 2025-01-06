(() => {
    let open = false;
    
    const header = document.querySelector('header#dashboard-header');
    const hamburger = header?.querySelector('button#dashboard-header-hamburger')

    if (
        !(header instanceof HTMLElement) ||
        !(hamburger instanceof HTMLButtonElement)
    ) return;

    hamburger.addEventListener('click', () => {
        open = !open;
        header.classList.toggle('-open')
        hamburger.innerText = open ? 'Close' : 'Menu';
        hamburger.ariaExpanded = open;
    })
})();