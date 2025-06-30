const form = document.getElementById('upload-form');
const visualizeBtnB = document.getElementById('visualize-btn-before');
const visualizeBtnA = document.getElementById('visualize-btn-after');
const resultDiv = document.getElementById('result');
const viewerDiv = document.getElementById('viewer');
const relviewerDiv = document.getElementById('relaxed-viewer');
const homeTab = document.getElementById('home-tab');
const historyTab = document.getElementById('history-tab');
const homeSection = document.getElementById('home-section');
const historySection = document.getElementById('history-section');
const historyTable = document.getElementById('history-table') ? document.getElementById('history-table').querySelector('tbody') : null;
let atoms;



// Utility function to fetch data from the server
async function fetchData(url, method = 'GET', body = null) {
  try {
    const options = { method };
    if (body) options.body = body;

    const response = await fetch(url, options);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'An error occurred');
    }
    return await response.json();
  } catch (error) {
    console.error(`Error fetching ${url}: ${error.message}`);
    resultDiv.innerHTML = `<p>Error: ${error.message}</p>`;
    throw error;
  }
}
// Function to map elements to colors
function getElementColor(element) {
  const colorMap = {
    H: '#ffffff',
    C: '#000000',
    O: '#ff0000',
    N: '#0000ff',
    S: '#ffff00',
  };
  return colorMap[element] || '#aaaaaa'; // Default color if element not found
}
// Utility function to render 3D viewer
let viewer = null; // Declare viewer globally

function renderViewer(container, atoms) {
  container.innerHTML = ''; // Clear previous content
  viewer = $3Dmol.createViewer(container, { backgroundColor: 'white' });

  atoms.forEach((atom) => {
    viewer.addSphere({
      center: { x: atom.x, y: atom.y, z: atom.z },
      radius: 0.5,
      color: getElementColor(atom.elem),
    });
  });

  viewer.zoomTo();
  viewer.render();
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const formData = new FormData(form);

  try {
    const data = await fetchData('/predict', 'POST', formData);

    if (data.prediction !== undefined) {
      document.getElementById('dynamic-result').innerHTML = `<p>${data.prediction.toFixed(6)}</p>`;
      window.relaxedPositions = data.relaxed_positions;  // Store relaxed positions globally
    } else {
      document.getElementById('dynamic-result').innerHTML = `<p>Error: No prediction received.</p>`;
    }
  } catch (error) {
    document.getElementById('dynamic-result').innerHTML = `<p>Error: ${error.message}</p>`;
  }
});






// Visualize Structure B (Original Structure)
visualizeBtnB.addEventListener('click', async () => {
  const formData = new FormData(form);
  const data = await fetchData('/visualize', 'POST', formData);
  atoms = data.atoms;
  renderViewer(viewerDiv, atoms);
});

// Visualize Structure A (Relaxed Structure)
visualizeBtnA.addEventListener('click', async () => {
  if (!window.relaxedPositions) {
    resultDiv.innerHTML = `<p>No relaxed positions found. Please run the prediction first.</p>`;
    return;
  }

  const formData = new FormData(form);
  formData.append('relaxed_positions', JSON.stringify(window.relaxedPositions));
  const data = await fetchData('/visualize', 'POST', formData);
  renderViewer(viewerDiv, data.atoms);
  renderViewer(relviewerDiv, data.relaxed_atoms);
});

// Tab navigation logic for Home section
homeTab.addEventListener('click', () => {
  homeSection.classList.remove('hidden');
  if (historySection) historySection.classList.add('hidden');
});

// Tab navigation logic for History section
if (historyTab && historySection) {
  historyTab.addEventListener('click', async () => {
    homeSection.classList.add('hidden');
    historySection.classList.remove('hidden');
    const history = await fetchData('/history');
    if (historyTable) {
      historyTable.innerHTML = '';
      history.forEach((entry) => {
        const row = document.createElement('tr');
        row.innerHTML = `
          <td><a href="/static/uploads/${entry.file_name}" download>${entry.file_name}</a></td>
          <td>${entry.predicted_energy}</td>
          <td>${entry.timestamp}</td>
        `;
        historyTable.appendChild(row);
      });
    }
  });
}
