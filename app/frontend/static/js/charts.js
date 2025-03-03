function renderPieChart(id, data, labels) {
  if (data.length === 0) {
    document.getElementById(id).innerHTML = '<p class="text-base-100 text-center">No data available.</p>';
    return;
  }

  const options = {
    series: data,
    labels: labels,
    chart: {
      type: 'pie', //'donut',
      width: 450,
      // height: 200,
      animations: {
        enabled: true,
        speed: 350,
      },
    },
    tooltip: {
      enabled: true,
      y: {
        formatter: function(value) {
          return value + " h";
        }
      }
    },
    // plotOptions: {
    //   pie: {
    //     donut: {
    //       size: '50%',
    //       background: 'transparent',
    //       labels: {
    //         show: true,
    //         total: {
    //           show: true,
    //           showAlways: true,
    //           label: 'Total',
    //         }
    //       }
    //     }
    //   }
    // },
    responsive: [
      {
        breakpoint: 640,
        options: {
          chart: {
            width: 300
          },
          legend: {
            position: 'bottom'
          }
        }
      },
      {
        breakpoint: 768,
        options: {
          chart: {
            width: 400
          },
          legend: {
            position: 'bottom'
          }
        }
      },
    ]
  };

  const chart = new ApexCharts(document.getElementById(id), options);
  chart.render();
}

function renderBarChart(id, data, labels) {
  if (data.length === 0) {
    document.getElementById(id).innerHTML = '<p class="text-base-100 text-center">No data available.</p>';
    return;
  }

  const options = {
    series: [{data: data}],
    xaxis: {categories: labels},
    chart: {
      type: 'bar',
      height: 175,
      animations: {
        enabled: true,
        speed: 350,
      },
    },
    plotOptions: {
      bar: {
        borderRadius: 4,
        borderRadiusApplication: 'end',
        horizontal: true,
      }
    },
    dataLabels: {
      enabled: true,
      formatter: function(value) {
        return value + " h";
      }
    },
    tooltip: {
      enabled: false
    },
    responsive: [
      {
        breakpoint: 767,
        options: {
          chart: {
            height: 300,
          },
          legend: {
            position: 'bottom',
          },
          plotOptions: {
            bar: {
              horizontal: false,
            }
          },
        }
      },
    ]
  };

  const chart = new ApexCharts(document.getElementById(id), options);
  chart.render();
}
