(function() {
  const container = document.querySelector('.webgl-hero-container');
  if (!container) return;

  // Create canvas element
  const canvas = document.createElement('canvas');
  canvas.id = 'webgl-canvas';
  canvas.style.position = 'absolute';
  canvas.style.top = '0';
  canvas.style.left = '0';
  canvas.style.width = '100%';
  canvas.style.height = '100%';
  canvas.style.zIndex = '1';
  canvas.style.pointerEvents = 'none';
  container.appendChild(canvas);

  let scene, camera, renderer, particles, coreSphere;
  let mouseX = 0, mouseY = 0;
  let targetX = 0, targetY = 0;

  const windowHalfX = window.innerWidth / 2;
  const windowHalfY = window.innerHeight / 2;

  function init() {
    try {
      scene = new THREE.Scene();
      
      // Camera
      camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 1, 1000);
      camera.position.z = 120;

      // Renderer
      renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(container.clientWidth, container.clientHeight);

      // Create Particle System
      const particleCount = 300;
      const geometry = new THREE.BufferGeometry();
      const positions = new Float32Array(particleCount * 3);
      const colors = new Float32Array(particleCount * 3);

      const color1 = new THREE.Color('#673de6'); // brand violet
      const color2 = new THREE.Color('#a855f7'); // light purple
      const color3 = new THREE.Color('#6366f1'); // indigo

      for (let i = 0; i < particleCount * 3; i += 3) {
        // Spherical placement
        const u = Math.random();
        const v = Math.random();
        const theta = u * 2.0 * Math.PI;
        const phi = Math.acos(2.0 * v - 1.0);
        const r = 40 + Math.random() * 20;

        positions[i] = r * Math.sin(phi) * Math.cos(theta);
        positions[i + 1] = r * Math.sin(phi) * Math.sin(theta);
        positions[i + 2] = r * Math.cos(phi);

        // Mix colors
        const mix = Math.random();
        let chosenColor;
        if (mix < 0.33) {
          chosenColor = color1;
        } else if (mix < 0.66) {
          chosenColor = color2;
        } else {
          chosenColor = color3;
        }

        colors[i] = chosenColor.r;
        colors[i + 1] = chosenColor.g;
        colors[i + 2] = chosenColor.b;
      }

      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

      // Circular particle texture
      const particleCanvas = document.createElement('canvas');
      particleCanvas.width = 16;
      particleCanvas.height = 16;
      const ctx = particleCanvas.getContext('2d');
      const grad = ctx.createRadialGradient(8, 8, 0, 8, 8, 8);
      grad.addColorStop(0, 'rgba(255, 255, 255, 1)');
      grad.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(8, 8, 8, 0, Math.PI * 2);
      ctx.fill();

      const texture = new THREE.CanvasTexture(particleCanvas);

      const material = new THREE.PointsMaterial({
        size: 3.0,
        map: texture,
        transparent: true,
        vertexColors: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false
      });

      particles = new THREE.Points(geometry, material);
      scene.add(particles);

      // Add floating wireframe sphere inside
      const sphereGeom = new THREE.SphereGeometry(24, 12, 12);
      const sphereMat = new THREE.MeshBasicMaterial({
        color: 0x673de6,
        wireframe: true,
        transparent: true,
        opacity: 0.08
      });
      coreSphere = new THREE.Mesh(sphereGeom, sphereMat);
      scene.add(coreSphere);

      document.addEventListener('mousemove', onDocumentMouseMove);
      window.addEventListener('resize', onWindowResize);

      animate();
    } catch (e) {
      console.warn("WebGL not supported or failed to initialize, falling back to CSS mesh gradient:", e);
      container.classList.add('mesh-gradient-fallback');
    }
  }

  function onDocumentMouseMove(event) {
    mouseX = (event.clientX - windowHalfX) * 0.1;
    mouseY = (event.clientY - windowHalfY) * 0.1;
  }

  function onWindowResize() {
    if (!camera || !renderer) return;
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  }

  function animate() {
    requestAnimationFrame(animate);

    targetX += (mouseX - targetX) * 0.05;
    targetY += (mouseY - targetY) * 0.05;

    if (particles) {
      particles.rotation.y += 0.0015;
      particles.rotation.x += 0.0008;
    }
    if (coreSphere) {
      coreSphere.rotation.y -= 0.001;
      coreSphere.rotation.z += 0.0005;
    }

    if (camera) {
      camera.position.x += (targetX - camera.position.x) * 0.05;
      camera.position.y += (-targetY - camera.position.y) * 0.05;
      camera.lookAt(scene.position);
    }

    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
  }

  // Load Three.js if not loaded
  if (typeof THREE === 'undefined') {
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
    script.onload = init;
    document.head.appendChild(script);
  } else {
    init();
  }
})();
