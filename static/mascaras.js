// Máscaras de digitação: formatam CPF e telefone enquanto a pessoa digita.
// Uso no HTML:  <input data-mascara="cpf">  ou  <input data-mascara="telefone">
(function () {
  function cpf(d) {
    d = d.slice(0, 11);
    return d.replace(/(\d{3})(\d)/, "$1.$2")
            .replace(/(\d{3})\.(\d{3})(\d)/, "$1.$2.$3")
            .replace(/(\d{3})\.(\d{3})\.(\d{3})(\d)/, "$1.$2.$3-$4");
  }

  function telefone(d) {
    d = d.slice(0, 11);
    if (d.length <= 2) return d.length ? "(" + d : "";
    var ddd = "(" + d.slice(0, 2) + ") ", resto = d.slice(2);
    // celular tem 9 dígitos depois do DDD (99999-9999), fixo tem 8 (9999-9999)
    var corte = resto.length > 8 ? 5 : 4;
    return ddd + (resto.length > corte ? resto.slice(0, corte) + "-" + resto.slice(corte) : resto);
  }

  var formatos = { cpf: cpf, telefone: telefone };

  function aplicar(campo) {
    var formatar = formatos[campo.dataset.mascara];
    if (formatar) campo.value = formatar(campo.value.replace(/\D/g, ""));
  }

  document.addEventListener("input", function (ev) {
    if (ev.target.dataset && ev.target.dataset.mascara) aplicar(ev.target);
  });

  // formata também valores que já vieram preenchidos do banco
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-mascara]").forEach(aplicar);
  });
})();
