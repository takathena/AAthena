/* NEXUS IoT - Mobile redirect (externalized from dashboard.html inline <script>). Must load synchronously at same place to preserve behavior. */
if (/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile|Tablet/i.test(navigator.userAgent) || window.innerWidth <= 768) {
    window.location.href = '/mobile';
}
