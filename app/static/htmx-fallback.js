(function () {
  "use strict";

  function createValidatorProgressController() {
    var indicator = document.getElementById("validator-indicator");
    var form = document.getElementById("validator-form");
    if (!indicator || !form) {
      return null;
    }

    var valueNode = indicator.querySelector("[data-progress-value]");
    var copyNode = indicator.querySelector("[data-progress-copy]");
    var progressbar = indicator.querySelector("[data-progressbar]");
    var timerId = null;
    var currentValue = 0;

    function updateCopy(value) {
      if (!copyNode) {
        return;
      }

      if (value < 18) {
        copyNode.textContent = "Uploading the workbook and rules...";
        return;
      }
      if (value < 42) {
        copyNode.textContent = "Checking workbook rules and preparing the verified file...";
        return;
      }
      if (value < 68) {
        copyNode.textContent = "Reviewing sheets, columns, and cell values...";
        return;
      }
      if (value < 90) {
        copyNode.textContent = "Building the validation summary and final workbook...";
        return;
      }
      copyNode.textContent = "Finishing the validation response...";
    }

    function render(value) {
      var safeValue = Math.max(0, Math.min(100, Math.round(value)));
      currentValue = safeValue;
      indicator.setAttribute("data-progress", String(safeValue));
      indicator.style.setProperty("--validator-progress", String(safeValue));
      if (valueNode) {
        valueNode.textContent = safeValue + "%";
      }
      if (progressbar) {
        progressbar.setAttribute("aria-valuenow", String(safeValue));
      }
      updateCopy(safeValue);
    }

    function clearTimer() {
      if (timerId) {
        window.clearTimeout(timerId);
        timerId = null;
      }
    }

    function scheduleTick() {
      clearTimer();
      timerId = window.setTimeout(function () {
        var nextValue = currentValue;
        if (nextValue < 18) {
          nextValue += 5;
        } else if (nextValue < 42) {
          nextValue += 4;
        } else if (nextValue < 68) {
          nextValue += 3;
        } else if (nextValue < 88) {
          nextValue += 2;
        } else if (nextValue < 94) {
          nextValue += 1;
        } else {
          return;
        }

        render(nextValue);
        scheduleTick();
      }, currentValue < 42 ? 220 : 320);
    }

    function start() {
      clearTimer();
      form.classList.add("is-validating");
      indicator.classList.add("htmx-request");
      indicator.classList.remove("is-complete", "is-error");
      render(8);
      scheduleTick();
    }

    function finish() {
      clearTimer();
      form.classList.remove("is-validating");
      indicator.classList.remove("is-error");
      indicator.classList.add("htmx-request", "is-complete");
      render(100);
      if (copyNode) {
        copyNode.textContent = "Validation finished. Loading the results...";
      }
      window.setTimeout(function () {
        indicator.classList.remove("htmx-request", "is-complete");
        render(0);
      }, 900);
    }

    function fail() {
      clearTimer();
      form.classList.remove("is-validating");
      indicator.classList.add("htmx-request", "is-error");
      render(Math.max(currentValue, 100));
      if (copyNode) {
        copyNode.textContent = "Validation request failed before the server could finish. Please try again.";
      }
      window.setTimeout(function () {
        indicator.classList.remove("htmx-request", "is-error");
        render(0);
      }, 2200);
    }

    return {
      form: form,
      start: start,
      finish: finish,
      fail: fail,
    };
  }

  function initFallback() {
    var validatorProgress = createValidatorProgressController();

    document.body.addEventListener("htmx:beforeRequest", function (event) {
      if (!validatorProgress || event.target !== validatorProgress.form) {
        return;
      }
      validatorProgress.start();
    });

    document.body.addEventListener("htmx:afterRequest", function (event) {
      if (!validatorProgress || event.target !== validatorProgress.form) {
        return;
      }
      validatorProgress.finish();
    });

    document.body.addEventListener("htmx:responseError", function (event) {
      if (!validatorProgress || event.target !== validatorProgress.form) {
        return;
      }
      validatorProgress.fail();
    });

    document.body.addEventListener("htmx:sendError", function (event) {
      if (!validatorProgress || event.target !== validatorProgress.form) {
        return;
      }
      validatorProgress.fail();
    });

    if (window.htmx) {
      return;
    }

    document.querySelectorAll("form[hx-post]").forEach(function (form) {
      form.addEventListener("submit", async function (event) {
        var targetSelector = form.getAttribute("hx-target");
        if (!targetSelector) {
          return;
        }

        var target = document.querySelector(targetSelector);
        if (!target) {
          return;
        }

        event.preventDefault();

        var indicatorSelector = form.getAttribute("hx-indicator");
        var indicator = indicatorSelector ? document.querySelector(indicatorSelector) : null;
        var isValidatorForm = validatorProgress && form === validatorProgress.form;

        form.classList.add("htmx-request");
        if (indicator) {
          indicator.classList.add("htmx-request");
        }
        if (isValidatorForm) {
          validatorProgress.start();
        }

        try {
          var response = await fetch(form.getAttribute("hx-post"), {
            method: "POST",
            body: new FormData(form),
            headers: { "X-Requested-With": "htmx-fallback" },
          });
          var html = await response.text();
          target.innerHTML = html;
          if (isValidatorForm) {
            validatorProgress.finish();
          }
        } catch (error) {
          target.innerHTML =
            '<div class="panel"><p>Request failed before the validator could respond. Please refresh and try again.</p></div>';
          if (isValidatorForm) {
            validatorProgress.fail();
          }
        } finally {
          form.classList.remove("htmx-request");
          if (indicator) {
            indicator.classList.remove("htmx-request");
          }
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initFallback);
  } else {
    initFallback();
  }
})();
