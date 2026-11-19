// Mensagens de validação em português. O navegador mostra os avisos dos campos no idioma dele
// (às vezes em inglês e com a data no formato mês/dia); aqui trocamos pelo texto da clínica.
(function () {
  function dataBR(valor) {
    // "2026-11-19" ou "2026-11-19T07:00" -> "19/11/2026" ou "19/11/2026 às 07:00"
    var p = valor.split("T"), d = p[0].split("-");
    return d[2] + "/" + d[1] + "/" + d[0] + (p[1] ? " às " + p[1] : "");
  }

  function ehData(campo) { return campo.type === "date" || campo.type === "datetime-local"; }

  // Alguns navegadores deixam digitar ano com 5 ou 6 dígitos (ex.: 131231) mesmo com max no campo
  function anoGrande(campo) { return ehData(campo) && /^\d{5,}-/.test(campo.value); }

  function mensagem(campo) {
    var v = campo.validity, data = ehData(campo);
    if (anoGrande(campo)) return "Digite o ano com 4 dígitos (ex.: 2026).";
    if (v.valueMissing) return campo.tagName === "SELECT" ? "Selecione uma opção." : "Preencha este campo.";
    if (v.badInput) return data ? "Data incompleta ou inválida." : "Valor inválido.";
    if (v.rangeUnderflow) return data ? "Escolha uma data a partir de " + dataBR(campo.min) + "."
                                      : "O valor mínimo é " + campo.min + ".";
    if (v.rangeOverflow) return data ? "Escolha uma data até " + dataBR(campo.max) + "."
                                     : "O valor máximo é " + campo.max + ".";
    if (v.stepMismatch) return campo.type === "datetime-local" ? "Escolha um horário de 5 em 5 minutos (ex.: 08:00, 08:05)."
                                                              : "Use um valor de " + campo.step + " em " + campo.step + ".";
    if (v.tooShort) return "Use pelo menos " + campo.minLength + " caracteres.";
    if (v.typeMismatch) return campo.type === "email" ? "Digite um e-mail válido (ex.: nome@email.com)." : "Valor inválido.";
    return "";
  }

  // "invalid" não sobe pela página, por isso a escuta é na fase de captura
  document.addEventListener("invalid", function (ev) {
    var campo = ev.target;
    campo.setCustomValidity("");
    if (!campo.validity.valid) campo.setCustomValidity(mensagem(campo));
  }, true);

  // ao corrigir o campo, limpa a mensagem para o navegador conferir de novo;
  // ano com mais de 4 dígitos já fica marcado como erro e o aviso aparece na hora
  ["input", "change"].forEach(function (tipo) {
    document.addEventListener(tipo, function (ev) {
      var campo = ev.target;
      if (!campo.setCustomValidity) return;
      campo.setCustomValidity(anoGrande(campo) ? mensagem(campo) : "");
      if (tipo === "change" && anoGrande(campo)) campo.reportValidity();
    }, true);
  });
})();
