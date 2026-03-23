    // Pull-to-Refresh handler
    (function() {
      const content = document.getElementById('screenContent');
      const indicator = document.getElementById('ptrIndicator');
      const ptrText = document.getElementById('ptrText');
      if (!content || !indicator) return;

      let startY = 0;
      let pulling = false;
      const THRESHOLD = 80;

      content.addEventListener('touchstart', (e) => {
        if (content.scrollTop <= 0) {
          startY = e.touches[0].clientY;
          pulling = true;
        }
      }, { passive: true });

      content.addEventListener('touchmove', (e) => {
        if (!pulling) return;
        const dy = e.touches[0].clientY - startY;
        if (dy > 10 && content.scrollTop <= 0) {
          indicator.classList.add('pulling');
          ptrText.textContent = dy > THRESHOLD ? 'Release to refresh' : 'Pull to refresh';
        }
      }, { passive: true });

      content.addEventListener('touchend', async () => {
        if (!pulling) return;
        pulling = false;

        if (indicator.classList.contains('pulling')) {
          const wasRelease = ptrText.textContent === 'Release to refresh';
          if (wasRelease) {
            indicator.classList.remove('pulling');
            indicator.classList.add('refreshing');
            ptrText.textContent = 'Starting sync...';

            const result = await triggerCloudRefresh();

            if (result.status === 'success') {
              ptrText.textContent = 'Fetching updated data...';
              await initData();
              ptrText.textContent = 'Data updated';
              setTimeout(() => {
                indicator.classList.remove('refreshing');
                location.reload();
              }, 1000);
            } else if (result.error && result.error.includes('not configured')) {
              ptrText.textContent = 'Cloud sync not configured yet';
              setTimeout(() => indicator.classList.remove('refreshing'), 2000);
            } else {
              ptrText.textContent = 'Sync failed - ' + (result.error || 'unknown error');
              setTimeout(() => indicator.classList.remove('refreshing'), 2000);
            }
          } else {
            indicator.classList.remove('pulling');
          }
        }
      });
    })();
